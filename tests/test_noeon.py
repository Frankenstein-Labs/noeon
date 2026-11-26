from pathlib import Path

from noeon.agents import default_registry
from noeon.contracts import Mission, MissionStatus
from noeon.execution import BoundedExecutor
from noeon.orchestrator import NoeonOrchestrator


def test_bounded_executor_runs_inside_workspace(tmp_path: Path) -> None:
    result = BoundedExecutor(tmp_path).run(["python", "-c", "print('ok')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_plan_is_persisted_without_ui(tmp_path: Path) -> None:
    mission = Mission(goal="inspect this repository", workspace=tmp_path)
    orchestrator = NoeonOrchestrator()
    plan = orchestrator.plan(mission)
    assert plan["goal"] == mission.goal


def test_missing_openhands_fails_explicitly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NOEON_MODEL", "test-model")
    mission = Mission(goal="perform a real engineering task", workspace=tmp_path, max_attempts=1)
    result = NoeonOrchestrator().run(mission)
    assert result.status == MissionStatus.FAILED
    assert result.error


def test_default_registry_has_skilled_specialists() -> None:
    registry = default_registry(max_agents=1000)
    assert len(registry.list()) >= 10
    assert all(agent.skills for agent in registry.list())
