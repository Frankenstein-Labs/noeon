from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import SkillRecord


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: str
    description: str
    permissions: frozenset[str] = frozenset({"read"})
    command: str | None = None
    module: str | None = None
    distribution: str | None = None
    env_keys: tuple[str, ...] = ()
    probe_args: tuple[str, ...] = ("--version",)


@dataclass
class ToolStatus:
    name: str
    available: bool
    kind: str
    detail: str = ""
    version: str = ""
    permissions: list[str] = field(default_factory=list)


class ToolRegistry:
    """Central tool catalog with real availability probes (no assumed tools)."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._cache: dict[str, ToolStatus] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda spec: spec.name)

    def probe(self, name: str, *, refresh: bool = False) -> ToolStatus:
        if not refresh and name in self._cache:
            return self._cache[name]
        spec = self._tools[name]
        available, detail, version = self._probe(spec)
        status = ToolStatus(name, available, spec.kind, detail, version, sorted(spec.permissions))
        self._cache[name] = status
        return status

    def status(self, *, refresh: bool = False) -> dict[str, ToolStatus]:
        return {spec.name: self.probe(spec.name, refresh=refresh) for spec in self.list()}

    def missing_for(self, record: SkillRecord) -> list[str]:
        missing: list[str] = []
        for tool in record.required_tools:
            if tool in self._tools and not self.probe(tool).available:
                missing.append(tool)
        return missing

    def _probe(self, spec: ToolSpec) -> tuple[bool, str, str]:
        if spec.kind == "native":
            return True, "provided by Noeon", ""
        if spec.env_keys:
            missing = [key for key in spec.env_keys if not os.getenv(key)]
            if missing:
                return False, f"missing environment variable(s): {', '.join(missing)}", ""
        if spec.command:
            path = shutil.which(spec.command)
            if not path:
                return False, f"binary not found: {spec.command}", ""
            return True, path, self._command_version(spec)
        if spec.module:
            if importlib.util.find_spec(spec.module) is None:
                return False, f"python module not found: {spec.module}", ""
            version = ""
            if spec.distribution:
                try:
                    version = importlib.metadata.version(spec.distribution)
                except importlib.metadata.PackageNotFoundError:
                    version = ""
            return True, f"module {spec.module}", version
        return False, "tool spec has no probe", ""

    def _command_version(self, spec: ToolSpec) -> str:
        assert spec.command
        try:
            completed = subprocess.run(
                [spec.command, *spec.probe_args], capture_output=True, text=True, timeout=5,
                check=False,
            )
            output = (completed.stdout or completed.stderr).strip().splitlines()
            return output[0][:80] if output else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    specs = [
        ToolSpec("terminal", "binary", "Run shell commands", frozenset({"execute"}), command="bash"),
        ToolSpec("git", "binary", "Version control", frozenset({"read", "write"}),
                 command="git", probe_args=("--version",)),
        ToolSpec("python", "binary", "Python interpreter", frozenset({"execute"}),
                 command="python3", module="sys"),
        ToolSpec("node", "binary", "Node.js runtime", frozenset({"execute"}), command="node"),
        ToolSpec("npm", "binary", "npm package manager", frozenset({"execute", "network"}),
                 command="npm"),
        ToolSpec("docker", "binary", "Container runtime", frozenset({"execute"}),
                 command="docker", probe_args=("--version",)),
        ToolSpec("curl", "binary", "HTTP client", frozenset({"network"}), command="curl"),
        ToolSpec("sqlite3", "binary", "SQLite CLI", frozenset({"read", "write"}), command="sqlite3"),
        ToolSpec("rg", "binary", "ripgrep search", frozenset({"read"}), command="rg"),
        ToolSpec("file_editor", "native", "Native file read/write tool", frozenset({"read", "write"})),
        ToolSpec("task_tracker", "native", "Native task planning tool", frozenset({"read", "write"})),
        ToolSpec("playwright_mcp", "service", "Playwright MCP server", frozenset({"network"}),
                 env_keys=("PLAYWRIGHT_MCP_COMMAND",)),
        ToolSpec("playwright", "python", "Playwright automation", frozenset({"network", "execute"}),
                 module="playwright", distribution="playwright"),
        ToolSpec("browser_use", "python", "browser-use agent", frozenset({"network", "execute"}),
                 module="browser_use", distribution="browser-use"),
        ToolSpec("crawl4ai", "python", "Crawl4AI extraction", frozenset({"network"}),
                 module="crawl4ai", distribution="crawl4ai"),
        ToolSpec("firecrawl", "service", "Firecrawl API", frozenset({"network"}),
                 env_keys=("FIRECRAWL_API_KEY",)),
        ToolSpec("github", "service", "GitHub API", frozenset({"network"}),
                 env_keys=("GITHUB_TOKEN",)),
        ToolSpec("mcp", "python", "Model Context Protocol client", frozenset({"network"}),
                 module="mcp", distribution="mcp"),
        ToolSpec("openhands", "python", "OpenHands Agent SDK", frozenset({"execute"}),
                 module="openhands.sdk", distribution="openhands-sdk"),
    ]
    for spec in specs:
        registry.register(spec)
    return registry


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]
