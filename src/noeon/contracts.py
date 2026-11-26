from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MissionStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class Mission(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    goal: str = Field(min_length=1)
    workspace: Path
    model: str | None = None
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    max_attempts: int = Field(default=3, ge=1, le=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionEvent(BaseModel):
    mission_id: UUID
    type: str
    status: MissionStatus | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MissionResult(BaseModel):
    mission_id: UUID
    status: MissionStatus
    summary: str
    attempts: int = 1
    events: list[MissionEvent] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None
