from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class BoundedExecutor:
    """Local development executor; production deployments should use a container runtime."""

    def __init__(self, workspace: Path, timeout_seconds: int = 120) -> None:
        self.workspace = workspace.resolve()
        self.timeout_seconds = timeout_seconds

    def run(self, command: list[str], *, timeout_seconds: int | None = None) -> CommandResult:
        if not command or any("\x00" in part for part in command):
            raise ValueError("command must be a non-empty, NUL-free argv")
        self.workspace.mkdir(parents=True, exist_ok=True)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.workspace)}
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
            )
            return CommandResult(command=" ".join(command), returncode=completed.returncode,
                                 stdout=completed.stdout, stderr=completed.stderr)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(command=" ".join(command), returncode=124,
                                 stdout=exc.stdout or "", stderr=exc.stderr or "", timed_out=True)
