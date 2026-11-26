from __future__ import annotations

from pathlib import Path

from skill_helpers import StubClient, make_universe, skill_text

from noeon.contracts import Mission, MissionStatus
from noeon.execution import BoundedExecutor
from noeon.orchestrator import NoeonOrchestrator
from noeon.skills import ExecutionPolicy, SkillExecutor, SkillSyncEngine, build_record
from noeon.skills.runtime import plan_mission

SKILL_BODY = """# FastAPI health endpoint

## When to use

Use when a FastAPI backend needs a health endpoint and its tests fail.

## Workflow

1. Inspect the application entry point.
2. Run `scripts/fix.py` to repair the status payload.
3. Run the test suite.

## Verification

`python3 -m pytest -q` must pass.
"""


def _git(workspace: Path, *args: str) -> None:
    result = BoundedExecutor(workspace).run(["git", *args])
    assert result.returncode == 0, result.stderr


def test_offline_mission_pipeline_uses_real_skills(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "app.py").write_text("def status():\n    return {}\n", encoding="utf-8")
    (workspace / "test_app.py").write_text(
        "from app import status\n\n\ndef test_status():\n"
        "    assert status() == {\"status\": \"ok\"}\n",
        encoding="utf-8",
    )
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "noeon@example.invalid")
    _git(workspace, "config", "user.name", "Noeon Test")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "initial failing state")

    before = BoundedExecutor(workspace).run(["python3", "-m", "pytest", "-q"])
    assert before.returncode != 0, "fixture must start with a failing test"

    text = skill_text(
        "fastapi-health-endpoint",
        "Add a health endpoint to the FastAPI backend API. Use when the API needs a status route.",
        license="MIT",
        allowed_tools=["Bash", "Read", "Write"],
        permissions=["execute"],
        body=SKILL_BODY,
    )
    script = (
        "from pathlib import Path\n\n"
        "Path('app.py').write_text("
        "'def status():\\n    return {\"status\": \"ok\"}\\n', encoding='utf-8')\n"
        "print('patched app.py')\n"
    )
    record = build_record(repository="acme/skills", commit="deadbeef", path="fastapi-health/SKILL.md",
                          text=text, declared_license="MIT").record
    record.metadata["scripts"] = ["scripts/fix.py"]

    universe = make_universe(tmp_path)
    try:
        universe.registry.upsert(record)
        engine = SkillSyncEngine(
            universe.registry,
            client=StubClient({
                ("acme/skills", "deadbeef", "fastapi-health/SKILL.md"): text,
                ("acme/skills", "deadbeef", "scripts/fix.py"): script,
            }),
            cache_dir=tmp_path / "cache",
        )
        installed = engine.install(record.skill_id)
        assert installed.installed, installed.reason

        plan = plan_mission(universe, "Add a health endpoint to the FastAPI backend API",
                            roles=["backend"], budget_tokens_per_role=2000)
        assert record.skill_id in plan.skill_ids
        assert plan.mission_id
        assert record.skill_id in {
            item["skill_id"] for item in universe.registry.mission_skills(plan.mission_id)
        }

        executor = SkillExecutor(universe.registry, workspace, skills_root=tmp_path / "skills",
                                 policy=ExecutionPolicy(allow_execution=True))
        execution = executor.run(record.skill_id, "scripts/fix.py", timeout_seconds=30)
        assert execution.returncode == 0, execution.stderr
        assert "patched app.py" in execution.stdout

        after = BoundedExecutor(workspace).run(["python3", "-m", "pytest", "-q"])
        assert after.returncode == 0, after.stdout + after.stderr

        mission = Mission(goal="Add a health endpoint to the FastAPI backend API",
                          workspace=workspace, require_changes=True)
        changed, error = NoeonOrchestrator().verify_workspace(mission)
        assert error == ""
        assert "app.py" in changed

        assert universe.registry.get(record.skill_id).installation_status.value == "installed"
        events = universe.registry.events(record.skill_id)
        assert any(event["operation"] == "execute" for event in events)
    finally:
        universe.close()


def test_mission_fails_without_openhands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NOEON_MODEL", "test-model")
    universe = make_universe(tmp_path)
    try:
        result = NoeonOrchestrator(skills=universe).run(
            Mission(goal="Add a health endpoint", workspace=tmp_path, max_attempts=1,
                    agent_role="backend")
        )
        assert result.status == MissionStatus.FAILED
        assert result.error
        assert (tmp_path / ".noeon" / "skills-plan.json").exists()
    finally:
        universe.close()
