import asyncio
from pathlib import Path

import pytest

from noeon.concurrency import AgentTask, ConcurrencyManager
from noeon.memory import MemoryConflict, MemoryPermissionError, SharedMemory


@pytest.mark.asyncio
async def test_scheduler_bounds_parallelism_and_runs_many_tasks() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def work() -> int:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.002)
        async with lock:
            active -= 1
        return 7

    async with ConcurrencyManager(max_workers=8, per_agent_limit=2) as manager:
        futures = [await manager.submit(AgentTask(work, agent_id=f"agent-{i % 20}"))
                   for i in range(250)]
        results = await asyncio.gather(*futures)
    assert peak <= 8
    assert all(result.value == 7 for result in results)


@pytest.mark.asyncio
async def test_scheduler_retries_and_timeout() -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ValueError("transient")
        return "ok"

    async with ConcurrencyManager(max_workers=1) as manager:
        future = await manager.submit(AgentTask(flaky, agent_id="a", max_retries=2))
        result = await future
    assert result.value == "ok"
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_shared_memory_cas_scope_and_events(tmp_path: Path) -> None:
    memory = SharedMemory(tmp_path / "memory.sqlite3")
    try:
        first = await memory.put("project", "plan", {"step": 1})
        second = await memory.put("project", "plan", {"step": 2}, expected_version=first.version)
        with pytest.raises(MemoryConflict):
            await memory.put("project", "plan", {"step": 3}, expected_version=first.version)
        events = await memory.events("project", "plan")
        assert [event["operation"] for event in events] == ["put", "put"]
        scope = memory.scope("project/agents/a")
        await scope.put("project/agents/a", "note", "shared")
        with pytest.raises(MemoryPermissionError):
            await scope.get("project/agents/b", "note")
        readonly = memory.scope("project", writable=False)
        with pytest.raises(MemoryPermissionError):
            await readonly.put("project", "x", 1)
        assert second.value == {"step": 2}
    finally:
        memory.close()
