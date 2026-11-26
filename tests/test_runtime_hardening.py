from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from noeon.concurrency import AgentTask, ConcurrencyManager
from noeon.memory import MemoryPermissionError, SharedMemory


@pytest.mark.asyncio
async def test_sync_tasks_do_not_block_the_scheduler() -> None:
    async with ConcurrencyManager(max_workers=2) as manager:
        blocking = await manager.submit(AgentTask(lambda: time.sleep(0.6), agent_id="sync"))
        started = time.monotonic()

        async def quick() -> str:
            return "quick"

        future = await manager.submit(AgentTask(quick, agent_id="async"))
        result = await future
        elapsed = time.monotonic() - started
        assert result.value == "quick"
        assert elapsed < 0.45, "the blocking sync task held the event loop"
        await blocking


@pytest.mark.asyncio
async def test_cancelled_task_finishes_as_cancelled() -> None:
    async def slow() -> int:
        await asyncio.sleep(0.3)
        return 1

    async with ConcurrencyManager(max_workers=1) as manager:
        blocker = await manager.submit(AgentTask(slow, agent_id="a"))
        task = AgentTask(slow, agent_id="b")
        queued = await manager.submit(task)
        assert manager.cancel(task.task_id) is True
        await blocker
        result = await queued
        assert result.cancelled is True


@pytest.mark.asyncio
async def test_memory_prefix_is_escaped(tmp_path: Path) -> None:
    memory = SharedMemory(tmp_path / "memory.sqlite3")
    try:
        await memory.put("ns", "a%b", 1)
        await memory.put("ns", "a_b", 2)
        await memory.put("ns", "axb", 3)
        percent = await memory.list("ns", prefix="a%")
        underscore = await memory.list("ns", prefix="a_")
        assert [entry.key for entry in percent] == ["a%b"]
        assert [entry.key for entry in underscore] == ["a_b"]
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_memory_scope_delete_and_events(tmp_path: Path) -> None:
    memory = SharedMemory(tmp_path / "memory.sqlite3")
    try:
        scope = memory.scope("missions/m1")
        entry = await scope.put("missions/m1", "plan", {"step": 1})
        assert await scope.delete("missions/m1", "plan", expected_version=entry.version)
        events = await scope.events("missions/m1", "plan")
        assert [event["operation"] for event in events] == ["put", "delete"]
        readonly = memory.scope("missions/m1", writable=False)
        with pytest.raises(MemoryPermissionError):
            await readonly.delete("missions/m1", "plan")
    finally:
        memory.close()
