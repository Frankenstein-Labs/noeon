from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents import AgentSkillManager, Assignment
from .dependencies import SkillDependencyManager
from .discovery import EmbeddingProvider, SkillDiscoveryEngine
from .executor import ExecutionPolicy, SkillExecutor
from .learning import SkillLearningEngine
from .loader import SkillLoader
from .mcp import MCPManager
from .model import SkillRecord
from .registry import SkillRegistry
from .tools import ToolRegistry
from .tools import default_registry as default_tool_registry

ROLE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "design": ("design", "ui", "ux", "wireframe", "prototype", "theme", "typography",
               "maquette", "charte graphique"),
    "frontend": ("frontend", "react", "next.js", "nextjs", "vue", "svelte", "angular",
                 "tailwind", "css", "interface", "page", "dashboard", "component",
                 "composant", "tableau de bord"),
    "backend": ("backend", "api", "server", "endpoint", "fastapi", "django", "flask",
                "nestjs", "express", "authentication", "authorization", "serveur",
                "authentification", "point de terminaison"),
    "database": ("database", "postgres", "postgresql", "mysql", "sqlite", "redis",
                 "schema", "migration", "sql", "base de données", "schéma"),
    "devops": ("deploy", "deployment", "docker", "kubernetes", "ci", "cd", "cloud",
               "infrastructure", "monitoring", "déploiement", "déployer", "supervision"),
    "security": ("security", "threat", "vulnerability", "audit", "pentest", "secret",
                 "cve", "sécurité", "vulnérabilité", "faille"),
    "research": ("research", "documentation", "compare", "investigate", "crawl", "browser",
                 "recherche", "veille", "comparer"),
    "ai-research": ("model", "llm", "rag", "embedding", "fine-tune", "training", "inference",
                    "modèle", "entraîner", "entraînement", "apprentissage", "évaluation",
                    "inférence"),
    "mobile": ("ios", "android", "mobile", "flutter", "react native", "swiftui"),
    "documentation": ("documentation", "readme", "spec", "report", "diagram",
                      "documenter", "rapport", "spécification"),
}


@dataclass
class SkillUniverse:
    registry: SkillRegistry
    tools: ToolRegistry
    discovery: SkillDiscoveryEngine
    loader: SkillLoader
    agents: AgentSkillManager
    dependencies: SkillDependencyManager
    executor: SkillExecutor
    mcp: MCPManager
    learning: SkillLearningEngine

    def close(self) -> None:
        self.registry.close()


@dataclass
class MissionSkillPlan:
    goal: str
    roles: list[str]
    assignments: dict[str, Assignment]
    context: str
    required_tools: list[str]
    missing_tools: dict[str, list[str]]
    skill_ids: list[str] = field(default_factory=list)
    mission_id: str | None = None

    def explain(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "mission_id": self.mission_id,
            "roles": self.roles,
            "skill_ids": self.skill_ids,
            "required_tools": self.required_tools,
            "missing_tools": self.missing_tools,
            "assignments": {role: assignment.explain() for role, assignment in self.assignments.items()},
            "context_tokens": _estimate(self.context),
            "context_chars": len(self.context),
        }


def build_universe(*, registry_path: str | Path = ".noeon/skills.sqlite3",
                   workspace: str | Path = ".", skills_root: str | Path = ".noeon/skills",
                   embeddings: EmbeddingProvider | None = None,
                   mcp_config: str | Path | None = None,
                   execution_policy: ExecutionPolicy | None = None) -> SkillUniverse:
    workspace_path = Path(workspace).expanduser().resolve()
    registry = SkillRegistry(registry_path)
    tools = default_tool_registry()
    discovery = SkillDiscoveryEngine(
        registry, embeddings=embeddings,
        vector_path=workspace_path / ".noeon" / "skill-vectors.jsonl",
    )
    loader = SkillLoader()
    deps = SkillDependencyManager(tools)
    agents = AgentSkillManager(registry, discovery, tools=tools, dependencies=deps, loader=loader)
    executor = SkillExecutor(registry, workspace_path, skills_root=skills_root, policy=execution_policy)
    mcp = MCPManager(mcp_config)
    learning = SkillLearningEngine(registry, workspace_path)
    return SkillUniverse(registry, tools, discovery, loader, agents, deps, executor, mcp, learning)


def _trigger_pattern(trigger: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(trigger)}(?![a-z0-9])")


def select_roles(goal: str, *, max_roles: int = 6) -> list[str]:
    lowered = goal.lower()
    selected = ["architect"]
    for role, triggers in ROLE_TRIGGERS.items():
        if role in selected:
            continue
        if any(_trigger_pattern(trigger).search(lowered) for trigger in triggers):
            selected.append(role)
    if "qa" not in selected:
        selected.append("qa")
    return selected[:max_roles]


def plan_mission(universe: SkillUniverse, goal: str, *, roles: list[str] | None = None,
                 budget_tokens_per_role: int = 3000, record: bool = True) -> MissionSkillPlan:
    selected = roles or select_roles(goal)
    assignments: dict[str, Assignment] = {}
    sections: list[str] = []
    required_tools: set[str] = set()
    missing: dict[str, list[str]] = {}
    skill_ids: list[str] = []

    for role in selected:
        try:
            assignment = universe.agents.assign(role, goal, budget_tokens=budget_tokens_per_role)
        except KeyError:
            continue
        assignments[role] = assignment
        if assignment.matches:
            sections.append(f"\n# Skills for the {role} agent\n{assignment.context.text}")
        for match in assignment.matches:
            required_tools.update(match.record.required_tools)
            if match.record.skill_id not in skill_ids:
                skill_ids.append(match.record.skill_id)
        if assignment.missing:
            missing.update(assignment.missing)

    context = (
        "# Noeon mission skill plan\n"
        f"Goal: {goal}\n\n"
        "Apply the sections below according to your role. Skills are read-only "
        "instructions; scripts run only through the skill executor.\n"
        + "\n".join(sections)
    )
    plan = MissionSkillPlan(goal, selected, assignments, context, sorted(required_tools),
                            missing, skill_ids)
    if record and skill_ids:
        mission_id = universe.registry.new_mission_id()
        scores = [(match.record.skill_id, match.score, f"role={role}")
                  for role, assignment in assignments.items() for match in assignment.matches]
        universe.registry.record_mission(mission_id, goal, scores)
        plan.mission_id = mission_id
    return plan


def _estimate(text: str) -> int:
    return (len(text) + 3) // 4


def usable_skill_count(registry: SkillRegistry) -> int:
    return sum(1 for _ in registry.iter_records(validation=None))


def summarize_registry(registry: SkillRegistry) -> dict[str, Any]:
    stats = registry.stats()
    records: list[SkillRecord] = registry.all()
    return {
        **stats,
        "categories_covered": sum(1 for count in stats["by_category"].values() if count > 0),
        "imported": sum(1 for r in records if r.installation_status.value in {"imported", "installed"}),
        "usable": sum(1 for r in records if r.is_usable),
        "with_scripts": sum(1 for r in records if r.metadata.get("scripts")),
        "with_dependencies": sum(1 for r in records if r.dependencies),
        "generated": sum(1 for r in records if r.origin.value == "generated"),
        "duplicates": sum(1 for r in records if r.duplicate_of),
        "top_sources": dict(list(stats["by_source"].items())[:10]),
    }
