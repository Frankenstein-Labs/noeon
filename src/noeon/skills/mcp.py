from __future__ import annotations

import importlib.util
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_COMMAND_ALLOWLIST = frozenset({"npx", "uvx", "node", "python3", "deno", "docker"})
DEFAULT_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "LANG", "TZ", "NODE_PATH", "NPM_CONFIG_CACHE",
    "GITHUB_TOKEN", "FIRECRAWL_API_KEY", "BRAVE_API_KEY", "SLACK_BOT_TOKEN",
})
_BLOCKED_ARG_PATTERNS = ("--privileged", "/var/run/docker.sock", "chmod 777")


@dataclass
class MCPServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


@dataclass
class MCPStatus:
    name: str
    configured: bool
    command_available: bool
    client_available: bool
    issues: list[str] = field(default_factory=list)
    detail: str = ""


class MCPManager:
    """Reads, validates and exposes MCP server definitions.

    Nothing is auto-connected. Validation is static: command allowlist, blocked
    flags, environment allowlist. Tool discovery needs a real MCP client and is
    reported as unavailable when the client library is missing.
    """

    def __init__(self, config_path: str | Path | None = None, *,
                 command_allowlist: frozenset[str] = DEFAULT_COMMAND_ALLOWLIST,
                 env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST) -> None:
        self.config_path = Path(
            config_path or os.getenv("NOEON_MCP_CONFIG") or ".noeon/mcp.json"
        ).expanduser()
        self.command_allowlist = command_allowlist
        self.env_allowlist = env_allowlist
        self._servers: list[MCPServer] = []
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            return
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        for name, raw in (data.get("mcpServers") or data.get("servers") or {}).items():
            self._servers.append(MCPServer(
                name=name,
                command=str(raw.get("command", "")),
                args=[str(arg) for arg in raw.get("args", [])],
                env={str(key): str(value) for key, value in (raw.get("env") or {}).items()},
                enabled=bool(raw.get("enabled", True)),
                description=str(raw.get("description", "")),
            ))

    @property
    def client_available(self) -> bool:
        return importlib.util.find_spec("mcp") is not None or importlib.util.find_spec("fastmcp") is not None

    def servers(self) -> list[MCPServer]:
        return list(self._servers)

    def register(self, server: MCPServer) -> None:
        self._servers = [existing for existing in self._servers if existing.name != server.name]
        self._servers.append(server)

    def validate(self) -> list[str]:
        issues: list[str] = []
        for server in self._servers:
            issues.extend(self._issues(server))
        return issues

    def _issues(self, server: MCPServer) -> list[str]:
        issues: list[str] = []
        if not server.name.strip():
            issues.append("server without a name")
        if not server.command.strip():
            issues.append(f"{server.name}: missing command")
        elif Path(server.command).name not in self.command_allowlist:
            issues.append(f"{server.name}: command '{server.command}' is not allowlisted")
        for arg in server.args:
            if any(pattern in arg for pattern in _BLOCKED_ARG_PATTERNS):
                issues.append(f"{server.name}: blocked argument '{arg}'")
        for key in server.env:
            if key not in self.env_allowlist:
                issues.append(f"{server.name}: environment key '{key}' is not allowlisted")
        return issues

    def status(self) -> list[MCPStatus]:
        statuses: list[MCPStatus] = []
        for server in self._servers:
            issues = self._issues(server)
            command_available = bool(shutil.which(server.command) or Path(server.command).exists())
            statuses.append(MCPStatus(
                name=server.name,
                configured=server.enabled,
                command_available=command_available,
                client_available=self.client_available,
                issues=issues,
                detail="ready" if not issues and command_available else "; ".join(issues),
            ))
        return statuses

    def to_openhands_mcp_config(self, *, include_disabled: bool = False) -> dict[str, Any]:
        """Return the standard `mcpServers` mapping for the OpenHands SDK."""
        servers: dict[str, Any] = {}
        for server in self._servers:
            if not server.enabled and not include_disabled:
                continue
            if self._issues(server):
                continue
            entry: dict[str, Any] = {"command": server.command, "args": server.args}
            if server.env:
                entry["env"] = {key: os.environ.get(key, "") for key in server.env}
            servers[server.name] = entry
        return {"mcpServers": servers}

    def discover_tools(self, server_name: str) -> list[str]:
        """Tool discovery requires a live MCP handshake; unavailable here without the client."""
        if not self.client_available:
            raise RuntimeError("MCP client library is not installed (pip install mcp)")
        raise RuntimeError(
            "live MCP tool discovery is not implemented in this slice; configure the server and "
            "let the OpenHands SDK perform the handshake"
        )
