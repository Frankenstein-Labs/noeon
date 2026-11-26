from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .model import InstallationStatus, SecurityDecision, SkillRecord, slugify
from .registry import SkillRegistry
from .security import is_script_path, scan_text

_INTERPRETERS = {
    ".py": lambda: sys.executable,
    ".sh": lambda: shutil.which("bash") or "/bin/sh",
    ".bash": lambda: shutil.which("bash") or "/bin/sh",
    ".js": lambda: shutil.which("node") or "node",
    ".mjs": lambda: shutil.which("node") or "node",
}


@dataclass(frozen=True)
class ExecutionResult:
    skill_id: str
    script: str
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    blocked: bool = False
    reason: str = ""
    duration_seconds: float = 0.0


@dataclass
class ExecutionPolicy:
    allow_execution: bool = False
    allowed_scripts: frozenset[str] = field(default_factory=frozenset)
    allow_network: bool = False
    timeout_seconds: int = 60
    max_output_chars: int = 20_000
    memory_limit_mb: int = 512
    runtime: str = "local"
    docker_image: str = "python:3.12-slim"


class SkillExecutor:
    """Runs a skill's declared scripts inside the workspace.

    Deny-by-default: the skill must be installed, valid, not blocked, declare the
    `execute` permission, and the script must live under `scripts/`. Secrets are
    not inherited from the host environment.
    """

    def __init__(self, registry: SkillRegistry, workspace: str | Path, *,
                 skills_root: str | Path = ".noeon/skills",
                 policy: ExecutionPolicy | None = None) -> None:
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()
        self.skills_root = Path(skills_root).expanduser().resolve()
        self.policy = policy or ExecutionPolicy()

    def skill_dir(self, record: SkillRecord) -> Path:
        return self.skills_root / slugify(record.skill_id.replace("/", "-"))

    def run(self, skill_id: str, script: str, args: list[str] | None = None, *,
            timeout_seconds: int | None = None) -> ExecutionResult:
        record = self.registry.get(skill_id)
        if record is None:
            return ExecutionResult(skill_id, script, "", 127, blocked=True, reason="unknown skill")
        guard = self._guard(record, script)
        if guard:
            return guard
        directory = self.skill_dir(record)
        script_path = (directory / script).resolve()
        if not script_path.is_file():
            return ExecutionResult(skill_id, script, "", 127, blocked=True, reason="script not found")

        interpreter = _INTERPRETERS.get(script_path.suffix.lower())
        if interpreter is None:
            return ExecutionResult(skill_id, script, "", 126, blocked=True,
                                   reason=f"unsupported script type: {script_path.suffix}")
        argv = [interpreter(), str(script_path), *(args or [])]
        timeout = timeout_seconds or self.policy.timeout_seconds
        env = self._environment()
        started = time.monotonic()
        try:
            if self.policy.runtime == "docker":
                result = self._run_docker(record, script_path, argv, env, timeout)
            else:
                result = subprocess.run(
                    argv, cwd=self.workspace, env=env, capture_output=True, text=True,
                    timeout=timeout, check=False, start_new_session=True,
                    preexec_fn=self._limits() if os.name == "posix" else None,
                )
            execution = ExecutionResult(
                skill_id=skill_id, script=script, command=" ".join(argv),
                returncode=result.returncode,
                stdout=_truncate(result.stdout, self.policy.max_output_chars),
                stderr=_truncate(result.stderr, self.policy.max_output_chars),
                duration_seconds=round(time.monotonic() - started, 3),
            )
        except subprocess.TimeoutExpired as exc:
            execution = ExecutionResult(
                skill_id=skill_id, script=script, command=" ".join(argv), returncode=124,
                stdout=_truncate(_decode(exc.stdout), self.policy.max_output_chars),
                stderr=_truncate(_decode(exc.stderr), self.policy.max_output_chars),
                timed_out=True, reason="timeout",
                duration_seconds=round(time.monotonic() - started, 3),
            )
        except FileNotFoundError as exc:
            execution = ExecutionResult(skill_id, script, " ".join(argv), 127, blocked=True,
                                        reason=f"missing interpreter: {exc}")
        self.registry.record_event(skill_id, "execute",
                                   f"{script} rc={execution.returncode} blocked={execution.blocked}")
        return execution

    def _guard(self, record: SkillRecord, script: str) -> ExecutionResult | None:
        def blocked(reason: str) -> ExecutionResult:
            return ExecutionResult(record.skill_id, script, "", 126, blocked=True, reason=reason)

        if not self.policy.allow_execution:
            return blocked("execution disabled by policy")
        if record.installation_status != InstallationStatus.INSTALLED:
            return blocked("skill is not installed")
        if record.validation_status.value != "valid":
            return blocked("skill is not valid")
        if record.security_status == SecurityDecision.BLOCK:
            return blocked("skill is blocked by the security scanner")
        if "execute" not in record.permissions:
            return blocked("skill does not declare the execute permission")
        if not script.startswith("scripts/") or not is_script_path(script):
            return blocked("only scripts/ paths can be executed")
        if self.policy.allowed_scripts and script not in self.policy.allowed_scripts:
            return blocked("script is not in the executor allowlist")
        path = self.skill_dir(record) / script
        if path.is_file():
            findings = scan_text(path.read_text(encoding="utf-8", errors="replace"),
                                 location=script, surface="script")
            if any(finding.severity.value in {"high", "critical"} for finding in findings):
                return blocked("script failed the execution-time security scan")
        return None

    def _environment(self) -> dict[str, str]:
        allowlist = os.getenv("NOEON_EXEC_ENV_ALLOWLIST", "PATH,LANG,LC_ALL,TZ")
        env = {key: os.environ[key] for key in allowlist.split(",") if key in os.environ}
        env["HOME"] = str(self.workspace)
        env["NOEON_SKILL_SANDBOX"] = "1"
        if not self.policy.allow_network:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                env.pop(key, None)
        return env

    def _limits(self):  # pragma: no cover - exercised through a subprocess
        import resource

        limit = self.policy.memory_limit_mb * 1024 * 1024

        def apply() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        return apply

    def _run_docker(self, record: SkillRecord, script_path: Path, argv: list[str],
                    env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
        docker = shutil.which("docker")
        if not docker:
            raise FileNotFoundError("docker binary not found")
        directory = self.skill_dir(record)
        relative = script_path.relative_to(directory)
        argv = ["docker", "run", "--rm", "--network", "none",
                "-v", f"{self.workspace}:/workspace", "-w", "/workspace",
                "-v", f"{directory}:/.skill:ro",
                "-e", "NOEON_SKILL_SANDBOX=1",
                self.policy.docker_image,
                "bash", "-lc",
                f"cd /workspace && ${{NOEON_DOCKER_INTERPRETER:-python3}} /.skill/{relative}"]
        return subprocess.run(argv, cwd=self.workspace, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)


def _truncate(value: str | None, limit: int) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + f"\n[truncated {len(text) - limit} chars]"


def _decode(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""
