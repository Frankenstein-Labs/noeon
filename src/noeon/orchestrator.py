from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .contracts import Mission, MissionEvent, MissionResult, MissionStatus
from .execution import BoundedExecutor
from .integrations import ModelRouter, load_deerflow_lead_agent, load_openhands


class NoeonOrchestrator:
    """Headless orchestration boundary between DeerFlow, OpenHands and the skill layer."""

    def __init__(self, *, event_sink: Callable[[MissionEvent], None] | None = None,
                 skills: Any | None = None) -> None:
        self.event_sink = event_sink
        self.router = ModelRouter()
        self.skills = skills

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

    def select_skills(self, mission: Mission) -> Any | None:
        if self.skills is None:
            return None
        from .skills.runtime import plan_mission

        roles = [mission.agent_role] if mission.agent_role else None
        return plan_mission(self.skills, mission.goal, roles=roles,
                            budget_tokens_per_role=mission.skill_budget_tokens)

    def execute_with_openhands(self, mission: Mission, skill_context: str = "") -> str:
        """Run a real OpenHands conversation; no fake completion is returned on failure."""
        Agent, Conversation, LLM, tools = load_openhands()
        model = self.router.select(mission.model)
        llm = LLM(model=model, api_key=None)
        selected = []
        for name in ("TerminalTool", "FileEditorTool", "TaskTrackerTool"):
            tool_class = getattr(tools, name, None)
            if tool_class is not None:
                selected.append(tool_class)
        agent = Agent(llm=llm, tools=[{"name": tool.name} for tool in selected])
        conversation = Conversation(agent=agent, workspace=str(mission.workspace))
        message = mission.goal
        if skill_context:
            message = f"{mission.goal}\n\n{skill_context}"
        conversation.send_message(message)
        conversation.run()
        return "OpenHands conversation completed"

    def verify_workspace(self, mission: Mission) -> tuple[list[str], str]:
        """Verify the workspace after execution and report the files the agent changed."""
        result = BoundedExecutor(mission.workspace, mission.timeout_seconds).run(
            ["git", "status", "--porcelain=v1"]
        )
        if result.returncode != 0:
            return [], result.stderr.strip() or "workspace verification failed"
        changed = [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]
        if mission.require_changes and not changed:
            return changed, "no changes were produced in the workspace"
        return changed, ""

    def run(self, mission: Mission) -> MissionResult:
        events: list[MissionEvent] = []
        emit = lambda *args, **kwargs: events.append(self._emit(mission, *args, **kwargs))
        emit("mission_started", "Mission accepted", MissionStatus.CREATED)
        attempts = 0
        skill_plan = None
        skills_used: list[str] = []
        try:
            emit("planning_started", "Building plan with DeerFlow", MissionStatus.PLANNING)
            plan = self.plan(mission)
            (mission.workspace / ".noeon").mkdir(parents=True, exist_ok=True)
            (mission.workspace / ".noeon" / "plan.json").write_text(
                json.dumps(plan, indent=2), encoding="utf-8"
            )
            emit("planning_completed", "Plan persisted", MissionStatus.PLANNING, plan=plan)

            skill_context = ""
            if self.skills is not None:
                skill_plan = self.select_skills(mission)
                if skill_plan is not None:
                    skills_used = list(skill_plan.skill_ids)
                    (mission.workspace / ".noeon" / "skills-plan.json").write_text(
                        json.dumps(skill_plan.explain(), indent=2), encoding="utf-8"
                    )
                    skill_context = skill_plan.context
                    emit("skills_selected", f"{len(skills_used)} skills selected",
                         MissionStatus.PLANNING, skills=skills_used,
                         roles=skill_plan.roles,
                         missing_tools=skill_plan.missing_tools)

            while attempts < mission.max_attempts:
                attempts += 1
                emit("execution_started", f"OpenHands attempt {attempts}", MissionStatus.EXECUTING)
                summary = self.execute_with_openhands(mission, skill_context)
                emit("testing_started", "Running workspace verification", MissionStatus.TESTING)
                changed, error = self.verify_workspace(mission)
                if error:
                    raise RuntimeError(error)
                emit("mission_succeeded", "Mission verified", MissionStatus.SUCCEEDED,
                     changed_files=changed)
                return MissionResult(
                    mission_id=mission.id, status=MissionStatus.SUCCEEDED, summary=summary,
                    attempts=attempts, events=events,
                    artifacts=[*changed, ".noeon/plan.json",
                               *([".noeon/skills-plan.json"] if skill_plan else [])],
                    skills_used=skills_used,
                )
            raise RuntimeError("maximum attempts reached")
        except Exception as exc:  # noqa: BLE001 - a failed mission must be reported, not raised
            emit("mission_failed", str(exc), MissionStatus.FAILED)
            return MissionResult(mission_id=mission.id, status=MissionStatus.FAILED,
                                 summary="Mission failed", attempts=attempts or 1,
                                 events=events, error=str(exc), skills_used=skills_used)
