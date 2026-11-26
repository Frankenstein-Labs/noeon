from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any


class IntegrationUnavailable(RuntimeError):
    pass


def _prepend_if_dir(value: str | None) -> None:
    if value:
        path = str(Path(value).expanduser().resolve())
        if path not in sys.path:
            sys.path.insert(0, path)


def _repo_default(*parts: str) -> str | None:
    root = Path(__file__).resolve().parents[2]
    candidate = root.joinpath(*parts)
    return str(candidate) if candidate.is_dir() else None


def load_deerflow_lead_agent() -> Any:
    """Load DeerFlow's published harness entry point from an explicit source checkout."""
    root = os.getenv("NOEON_DEERFLOW_BACKEND") or _repo_default(
        "vendor", "deer-flow", "backend", "packages", "harness"
    )
    _prepend_if_dir(root)
    try:
        module = importlib.import_module("deerflow.agents")
        return module.make_lead_agent
    except (ImportError, AttributeError) as exc:
        raise IntegrationUnavailable(
            "DeerFlow is not importable from "
            f"{root or 'vendor/deer-flow/backend/packages/harness'}: {exc}. "
            "Set NOEON_DEERFLOW_BACKEND to its backend directory and install its dependencies."
        ) from exc


def load_openhands() -> tuple[Any, Any, Any, Any]:
    """Load OpenHands SDK classes, optionally from a checked-out SDK source tree."""
    root = os.getenv("NOEON_OPENHANDS_SDK") or _repo_default(
        "vendor", "openhands-software-agent-sdk", "openhands-sdk"
    )
    _prepend_if_dir(root)
    try:
        sdk = importlib.import_module("openhands.sdk")
        tools = importlib.import_module("openhands.tools")
        return sdk.Agent, sdk.Conversation, sdk.LLM, tools
    except (ImportError, AttributeError) as exc:
        raise IntegrationUnavailable(
            f"OpenHands SDK is not importable from {root or 'the installed packages'}: {exc}. "
            "Install noeon[openhands] or set NOEON_OPENHANDS_SDK."
        ) from exc


class ModelRouter:
    """Provider-neutral model selection; provider construction stays in the host application."""

    def __init__(self, default_model: str | None = None) -> None:
        self.default_model = default_model or os.getenv("NOEON_MODEL", "")

    def select(self, requested: str | None = None) -> str:
        model = requested or self.default_model
        if not model:
            raise ValueError("No model selected; set NOEON_MODEL or pass Mission.model")
        return model
