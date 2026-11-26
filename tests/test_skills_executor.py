from __future__ import annotations

from pathlib import Path

from skill_helpers import new_registry, skill_text

from noeon.skills import (
    ExecutionPolicy,
    InstallationStatus,
    SkillDependencyManager,
    SkillExecutor,
    build_record,
    default_tool_registry,
)


def _install_skill(tmp_path: Path, registry, *, script: str, permissions=("execute",),
                   body_script: str = "scripts/ok.py", name: str = "runner"):
    text = skill_text(
        name,
        "Run a bounded helper script. Use when a mission needs the helper.",
        license="MIT",
        allowed_tools=["Bash"],
        permissions=list(permissions),
        body=f"# Runner\n\nRun `{body_script}` and check the output.\n",
    )
    record = build_record(repository="acme/skills", commit="abc", path=f"{name}/SKILL.md",
                          text=text, declared_license="MIT").record
    record.installation_status = InstallationStatus.INSTALLED
    record.metadata["scripts"] = [body_script]
    registry.upsert(record)
    directory = tmp_path / "skills" / "acme-skills-runner"
    script_path = directory / body_script
    script_path.parent.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    script_path.write_text(script, encoding="utf-8")
    return record


def test_executor_runs_allowed_script(tmp_path: Path) -> None:
    registry = new_registry(tmp_path)
    try:
        record = _install_skill(tmp_path, registry, script="print('hello from skill')\n")
        executor = SkillExecutor(registry, tmp_path, skills_root=tmp_path / "skills",
                                 policy=ExecutionPolicy(allow_execution=True))
        result = executor.run(record.skill_id, "scripts/ok.py")
        assert result.returncode == 0, result.stderr
        assert "hello from skill" in result.stdout
    finally:
        registry.close()


def test_executor_is_deny_by_default(tmp_path: Path) -> None:
    registry = new_registry(tmp_path)
    try:
        record = _install_skill(tmp_path, registry, script="print('nope')\n")
        executor = SkillExecutor(registry, tmp_path, skills_root=tmp_path / "skills")
        result = executor.run(record.skill_id, "scripts/ok.py")
        assert result.blocked
        assert "policy" in result.reason
    finally:
        registry.close()


def test_executor_requires_execute_permission(tmp_path: Path) -> None:
    registry = new_registry(tmp_path)
    try:
        record = _install_skill(tmp_path, registry, script="print('x')\n", permissions=("read",),
                                body_script="scripts/ok.py")
        record.required_tools = []
        record.permissions = ["read"]
        registry.upsert(record)
        executor = SkillExecutor(registry, tmp_path, skills_root=tmp_path / "skills",
                                 policy=ExecutionPolicy(allow_execution=True))
        result = executor.run(record.skill_id, "scripts/ok.py")
        assert result.blocked
        assert "execute permission" in result.reason
    finally:
        registry.close()


def test_executor_only_runs_scripts_directory(tmp_path: Path) -> None:
    registry = new_registry(tmp_path)
    try:
        record = _install_skill(tmp_path, registry, script="print('x')\n",
                               body_script="scripts/ok.py")
        (tmp_path / "skills" / "acme-skills-runner" / "evil.py").write_text("print('evil')\n")
        executor = SkillExecutor(registry, tmp_path, skills_root=tmp_path / "skills",
                                 policy=ExecutionPolicy(allow_execution=True))
        result = executor.run(record.skill_id, "../evil.py")
        assert result.blocked
        assert "scripts/" in result.reason
    finally:
        registry.close()


def test_executor_honours_timeout(tmp_path: Path) -> None:
    registry = new_registry(tmp_path)
    try:
        record = _install_skill(tmp_path, registry, script="import time\ntime.sleep(5)\n")
        executor = SkillExecutor(registry, tmp_path, skills_root=tmp_path / "skills",
                                 policy=ExecutionPolicy(allow_execution=True))
        result = executor.run(record.skill_id, "scripts/ok.py", timeout_seconds=1)
        assert result.timed_out
        assert result.returncode == 124
    finally:
        registry.close()


def test_dependency_manager_reports_real_availability(tmp_path: Path) -> None:
    text = skill_text(
        "deps",
        "A skill with dependencies. Use when checking dependency resolution.",
        license="MIT",
        dependencies=["python:json", "python:module_that_does_not_exist_xyz", "git"],
    )
    record = build_record(repository="acme/skills", commit="abc", path="deps/SKILL.md",
                          text=text, declared_license="MIT").record
    manager = SkillDependencyManager(default_tool_registry())
    statuses = {status.name: status for status in manager.check(record)}
    assert statuses["json"].available is True
    assert statuses["module_that_does_not_exist_xyz"].available is False
    assert statuses["git"].available is True
    plan = manager.install_plan(record)
    assert any(command[:2] == ["pip", "install"] for command in plan)


def test_native_tools_are_reported_available() -> None:
    registry = default_tool_registry()
    assert registry.probe("file_editor").available is True
    assert registry.probe("task_tracker").available is True
