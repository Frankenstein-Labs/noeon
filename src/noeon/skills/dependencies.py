from __future__ import annotations

import importlib.util
import os
import re
import shutil
from dataclasses import dataclass

from .model import SkillRecord
from .tools import ToolRegistry

_PYTHON_DIST = {
    "pandas": "pandas", "numpy": "numpy", "pyyaml": "yaml", "yaml": "yaml",
    "pillow": "PIL", "beautifulsoup4": "bs4", "scikit-learn": "sklearn",
    "opencv-python": "cv2", "python-dotenv": "dotenv", "httpx": "httpx",
    "requests": "requests", "pydantic": "pydantic", "playwright": "playwright",
    "crawl4ai": "crawl4ai", "openai": "openai", "anthropic": "anthropic",
    "transformers": "transformers", "torch": "torch", "datasets": "datasets",
    "sentence-transformers": "sentence_transformers", "faiss-cpu": "faiss",
    "chromadb": "chromadb", "qdrant-client": "qdrant_client", "fastapi": "fastapi",
}
_BINARY_HINTS = {
    "git", "docker", "node", "npm", "pnpm", "yarn", "bun", "curl", "wget", "rg",
    "jq", "ffmpeg", "psql", "sqlite3", "kubectl", "helm", "terraform", "gh",
    "deno", "uv", "go", "cargo", "rustc", "swift", "java", "mvn", "gradle",
}


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    kind: str
    available: bool
    detail: str = ""

    @property
    def install_hint(self) -> str:
        if self.available:
            return ""
        if self.kind == "python":
            return f"pip install {self.name}"
        if self.kind == "npm":
            return f"npm install -g {self.name}"
        if self.kind == "binary":
            return f"install the '{self.name}' binary"
        if self.kind == "env":
            return f"set environment variable {self.name}"
        return f"provide {self.name}"


class SkillDependencyManager:
    """Checks declared dependencies against the real environment; never installs silently."""

    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self.tools = tools or ToolRegistry()

    def check(self, record: SkillRecord) -> list[DependencyStatus]:
        statuses: list[DependencyStatus] = []
        for dependency in record.dependencies:
            statuses.append(self._check_one(dependency))
        for tool in record.required_tools:
            if tool in {spec.name for spec in self.tools.list()}:
                probe = self.tools.probe(tool)
                statuses.append(DependencyStatus(tool, "tool", probe.available, probe.detail))
        return statuses

    def missing(self, record: SkillRecord) -> list[DependencyStatus]:
        return [status for status in self.check(record) if not status.available]

    def install_plan(self, record: SkillRecord) -> list[list[str]]:
        plan: list[list[str]] = []
        for status in self.missing(record):
            if status.kind == "python":
                plan.append(["pip", "install", status.name])
            elif status.kind == "npm":
                plan.append(["npm", "install", "-g", status.name])
        return plan

    def _check_one(self, dependency: str) -> DependencyStatus:
        raw = dependency.strip()
        if not raw:
            return DependencyStatus(raw, "unknown", False, "empty dependency")
        kind, _, name = raw.partition(":")
        if not name:
            name, kind = raw, ""
        lowered = name.lower()

        if kind in {"env", "secret"}:
            return DependencyStatus(name, "env", bool(os.getenv(name)), "environment variable")
        if kind in {"bin", "binary"}:
            path = shutil.which(name)
            return DependencyStatus(name, "binary", bool(path), path or "")
        if kind == "npm":
            return DependencyStatus(name, "npm", bool(shutil.which("npm")), "npm present" if shutil.which("npm") else "npm missing")
        if kind in {"pip", "python"}:
            module = _PYTHON_DIST.get(lowered, lowered.replace("-", "_"))
            return DependencyStatus(name, "python", _has_module(module), f"module {module}")
        if kind == "tool":
            specs = {spec.name for spec in self.tools.list()}
            if name in specs:
                probe = self.tools.probe(name)
                return DependencyStatus(name, "tool", probe.available, probe.detail)
            return DependencyStatus(name, "tool", False, "unknown tool")

        if lowered in _BINARY_HINTS:
            path = shutil.which(lowered)
            return DependencyStatus(name, "binary", bool(path), path or "")
        module = _PYTHON_DIST.get(lowered, re.sub(r"[^a-z0-9_]", "_", lowered))
        if _has_module(module):
            return DependencyStatus(name, "python", True, f"module {module}")
        path = shutil.which(lowered)
        if path:
            return DependencyStatus(name, "binary", True, path)
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", name):
            return DependencyStatus(name, "env", bool(os.getenv(name)), "environment variable")
        return DependencyStatus(name, "python", False, f"module {module} not importable")


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False
