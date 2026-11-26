from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tool_permissions: frozenset[str] = frozenset()


@dataclass
class AgentSpec:
    name: str
    role: str
    skills: list[Skill] = field(default_factory=list)
    max_concurrency: int = 1


class AgentRegistry:
    """Declarative registry; execution remains owned by the integrated engines."""

    def __init__(self, max_agents: int = 1000) -> None:
        if max_agents < 1:
            raise ValueError("max_agents must be positive")
        self.max_agents = max_agents
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        if len(self._agents) >= self.max_agents and spec.name not in self._agents:
            raise RuntimeError("agent capacity reached")
        if spec.name in self._agents:
            raise ValueError(f"agent already registered: {spec.name}")
        self._agents[spec.name] = spec

    def get(self, name: str) -> AgentSpec:
        return self._agents[name]

    def list(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def grant_skill(self, agent_name: str, skill: Skill) -> None:
        agent = self.get(agent_name)
        if skill.name not in {item.name for item in agent.skills}:
            agent.skills.append(skill)


def default_registry(max_agents: int = 1000) -> AgentRegistry:
    registry = AgentRegistry(max_agents=max_agents)
    baseline = [
        Skill("repository-analysis", "Map repository structure and dependencies", frozenset({"read"})),
        Skill("implementation", "Edit source files with repository-local tools", frozenset({"read", "write"})),
        Skill("testing", "Run tests and interpret failures", frozenset({"read", "execute"})),
        Skill("debugging", "Diagnose and repair failed executions", frozenset({"read", "write", "execute"})),
        Skill("security-review", "Review permissions, secrets and unsafe changes", frozenset({"read"})),
    ]
    for role in ("architect", "backend", "frontend", "devops", "database", "security", "qa", "debugger", "performance", "research"):
        registry.register(AgentSpec(name=role, role=role, skills=list(baseline)))
    return registry
