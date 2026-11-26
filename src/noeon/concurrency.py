from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Self, TypeVar
from uuid import UUID, uuid4

T = TypeVar("T")


class SchedulerClosed(RuntimeError):
    pass


class QueueFull(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentTask[T]:
    """A unit of work. The callable is invoked only when a worker admits the task."""

    run: Callable[[], Awaitable[T] | T]
    agent_id: str
    task_id: UUID = field(default_factory=uuid4)
    priority: int = 100
    max_retries: int = 0
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult[T]:
    task_id: UUID
    agent_id: str
    value: T | None
    error: BaseException | None
    attempts: int
    duration_seconds: float
    cancelled: bool = False


@dataclass(order=True)
class _QueuedTask:
    priority: int
    sequence: int
    task: AgentTask[Any] | None = field(compare=False)
    future: asyncio.Future[TaskResult[Any]] | None = field(compare=False)


class ConcurrencyManager:
    """High-cardinality task scheduler with bounded worker concurrency.

    Tasks remain lightweight queue entries until a worker starts them. Per-agent
    limits prevent one agent from monopolizing the worker pool.
    """

    _STOP_PRIORITY = 10**12

    def __init__(self, *, max_workers: int = 64, per_agent_limit: int = 4,
                 queue_size: int = 100_000) -> None:
        if max_workers < 1 or per_agent_limit < 1 or queue_size < 1:
            raise ValueError("max_workers, per_agent_limit and queue_size must be positive")
        self.max_workers = max_workers
        self.per_agent_limit = per_agent_limit
        self.queue_size = queue_size
        self._queue: asyncio.PriorityQueue[_QueuedTask | object] = asyncio.PriorityQueue(queue_size)
        self._sequence = count()
        self._workers: list[asyncio.Task[None]] = []
        self._active: defaultdict[str, int] = defaultdict(int)
        self._active_condition = asyncio.Condition()
        self._pending: dict[UUID, asyncio.Future[TaskResult[Any]]] = {}
        self._cancelled: set[UUID] = set()
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise SchedulerClosed("scheduler is closed")
        if self._started:
            return
        self._started = True
        self._workers = [asyncio.create_task(self._worker(i), name=f"noeon-worker-{i}")
                         for i in range(self.max_workers)]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task_id in list(self._pending):
            self.cancel(task_id)
        if self._started:
            await self._queue.join()
            for _ in self._workers:
                await self._queue.put(_QueuedTask(self._STOP_PRIORITY, next(self._sequence), None, None))
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def submit(self, task: AgentTask[T]) -> asyncio.Future[TaskResult[T]]:
        if self._closed:
            raise SchedulerClosed("scheduler is closed")
        if not self._started:
            await self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[TaskResult[T]] = loop.create_future()
        self._pending[task.task_id] = future
        try:
            self._queue.put_nowait(_QueuedTask(task.priority, next(self._sequence), task, future))
        except asyncio.QueueFull as exc:
            self._pending.pop(task.task_id, None)
            raise QueueFull(f"scheduler queue limit reached ({self.queue_size})") from exc
        return future

    def cancel(self, task_id: UUID) -> bool:
        future = self._pending.get(task_id)
        if future is None or future.done():
            return False
        self._cancelled.add(task_id)
        return True

    async def wait(self, task_id: UUID) -> TaskResult[Any]:
        future = self._pending.get(task_id)
        if future is None:
            raise KeyError(task_id)
        return await future

    async def drain(self) -> None:
        await self._queue.join()
        async with self._active_condition:
            while self._active:
                await self._active_condition.wait()

    def active_counts(self) -> dict[str, int]:
        return dict(self._active)

    async def _worker(self, _: int) -> None:
        while True:
            item = await self._queue.get()
            if isinstance(item, _QueuedTask) and item.task is None:
                self._queue.task_done()
                return
            queued = item
            task = queued.task
            assert task is not None and queued.future is not None
            if task.task_id in self._cancelled:
                self._cancelled.discard(task.task_id)
                self._finish(task, queued.future, TaskResult(task.task_id, task.agent_id, None,
                                                              None, 0, 0.0, cancelled=True))
                self._queue.task_done()
                continue
            async with self._active_condition:
                while self._active[task.agent_id] >= self.per_agent_limit:
                    await self._active_condition.wait()
                self._active[task.agent_id] += 1
            try:
                result = await self._execute(task)
                self._finish(task, queued.future, result)
            finally:
                async with self._active_condition:
                    self._active[task.agent_id] -= 1
                    if self._active[task.agent_id] == 0:
                        del self._active[task.agent_id]
                    self._active_condition.notify_all()
                self._queue.task_done()

    async def _execute(self, task: AgentTask[T]) -> TaskResult[T]:
        started = time.monotonic()
        attempts = 0
        last_error: BaseException | None = None
        while attempts <= task.max_retries:
            attempts += 1
            try:
                if task.timeout_seconds is None:
                    value = await self._invoke(task)
                else:
                    value = await asyncio.wait_for(self._invoke(task), task.timeout_seconds)
                return TaskResult(task.task_id, task.agent_id, value, None, attempts,
                                  time.monotonic() - started)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - task errors are returned to the caller
                last_error = exc
        return TaskResult(task.task_id, task.agent_id, None, last_error, attempts,
                          time.monotonic() - started)

    @staticmethod
    async def _invoke(task: AgentTask[Any]) -> Any:
        # Sync callables must not run on the worker's event loop: one blocking task
        # would otherwise stall every other agent sharing the scheduler.
        if inspect.iscoroutinefunction(task.run):
            value = task.run()
        else:
            value = await asyncio.to_thread(task.run)
        if inspect.isawaitable(value):
            value = await value
        return value

    def _finish(self, task: AgentTask[Any], future: asyncio.Future[TaskResult[Any]],
                result: TaskResult[Any]) -> None:
        self._pending.pop(task.task_id, None)
        if not future.done():
            future.set_result(result)
