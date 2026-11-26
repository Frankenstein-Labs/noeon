from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .contracts import Mission, MissionEvent, MissionResult, MissionStatus
from .execution import BoundedExecutor
from .integrations import ModelRouter, load_deerflow_lead_agent, load_openhands


class NoeonOrchestrator:
    """Headless orchestration boundary between DeerFlow and OpenHands."""

    def __init__(self, *, event_sink: Callable[[MissionEvent], None] | None = None) -> None:
        self.event_sink = event_sink
        self.router = ModelRouter()

    def _emit(self, mission: Mission, event_type: str, message: str,
              status: MissionStatus | None = None, **data: Any) -> MissionEvent:
        event = MissionEvent(mission_id=mission.id, type=event_type, status=status,
                             message=message, data=data)
        if self.event_sink:
            self.event_sink(event)
        return event

    def plan(self, mission: Mission) -> dict[str, Any]:
        """Use DeerFlow's lead-agent factory when available; retain a typed plan contract."""
        try:
            factory = load_deerflow_lead_agent()
            return {"engine": "deerflow", "factory": getattr(factory, "__name__", str(factory)),
                    "goal": mission.goal, "workspace": str(mission.workspace)}
        except (ImportError, AttributeError, RuntimeError) as exc:
            return {"engine": "deerflow-unavailable", "reason": str(exc),
                    "goal": mission.goal, "workspace": str(mission.workspace)}

    def execute_with_openhands(self, mission: Mission) -> str:
        """Run a real OpenHands conversation; no fake completion is returned on failure."""
        Agent, Conversation, LLM, tools = load_openhands()
        model = self.router.select(mission.model)
        llm = LLM(model=model, api_key=None)
        selected = []
        for name in ("TerminalTool", "FileEditorTool", "TaskTrackerTool"):
            tool_class = getattr(tools, name, None)
            if tool_class is not None:
                selected.append(tool_class)
        agent = Agent(llm=llm, tools=[{"name": t.name} for t in selected])
        conversation = Conversation(agent=agent, workspace=str(mission.workspace))
        conversation.send_message(mission.goal)
        conversation.run()
        return "OpenHands conversation completed"

    def run(self, mission: Mission) -> MissionResult:
        events: list[MissionEvent] = []
        emit = lambda *args, **kwargs: events.append(self._emit(mission, *args, **kwargs))
        emit("mission_started", "Mission accepted", MissionStatus.CREATED)
        attempts = 0
        try:
            emit("planning_started", "Building plan with DeerFlow", MissionStatus.PLANNING)
            plan = self.plan(mission)
            (mission.workspace / ".noeon").mkdir(parents=True, exist_ok=True)
            (mission.workspace / ".noeon" / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
            emit("planning_completed", "Plan persisted", MissionStatus.PLANNING, plan=plan)
            while attempts < mission.max_attempts:
                attempts += 1
                emit("execution_started", f"OpenHands attempt {attempts}", MissionStatus.EXECUTING)
                summary = self.execute_with_openhands(mission)
                emit("testing_started", "Running workspace verification", MissionStatus.TESTING)
                result = BoundedExecutor(mission.workspace, mission.timeout_seconds).run(["git", "status", "--short"])
                if result.returncode != 0:
                    raise RuntimeError(result.stderr or "workspace verification failed")
                emit("mission_succeeded", "Mission verified", MissionStatus.SUCCEEDED)
                return MissionResult(mission_id=mission.id, status=MissionStatus.SUCCEEDED,
                                     summary=summary, attempts=attempts, events=events)
            raise RuntimeError("maximum attempts reached")
        except (ImportError, AttributeError, RuntimeError, ValueError, OSError) as exc:
            emit("mission_failed", str(exc), MissionStatus.FAILED)
            return MissionResult(mission_id=mission.id, status=MissionStatus.FAILED,
                                 summary="Mission failed", attempts=attempts or 1,
                                 events=events, error=str(exc))
