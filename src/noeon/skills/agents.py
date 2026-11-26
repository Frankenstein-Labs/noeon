from __future__ import annotations

from dataclasses import dataclass, field

from noeon.agents import AgentRegistry, Skill

from .dependencies import DependencyStatus, SkillDependencyManager
from .discovery import SkillDiscoveryEngine, SkillMatch
from .loader import SkillContext, SkillLoader
from .model import SecurityDecision, SkillRecord
from .registry import SkillRegistry
from .taxonomy import RoleProfile, profile_for
from .tools import ToolRegistry


@dataclass
class Assignment:
    role: str
    goal: str
    matches: list[SkillMatch]
    context: SkillContext
    missing: dict[str, list[str]] = field(default_factory=dict)

    @property
    def skill_ids(self) -> list[str]:
        return [match.record.skill_id for match in self.matches]

    def explain(self) -> dict[str, object]:
        return {
            "role": self.role,
            "goal": self.goal,
            "skills": [match.explain() for match in self.matches],
            "loaded": self.context.skill_ids,
            "estimated_tokens": self.context.estimated_tokens,
            "truncated": self.context.truncated,
            "missing_tools": self.missing,
        }


class AgentSkillManager:
    """Binds roles to real catalog skills, with per-role limits and lending rules."""

    def __init__(self, registry: SkillRegistry, discovery: SkillDiscoveryEngine, *,
                 tools: ToolRegistry | None = None,
                 dependencies: SkillDependencyManager | None = None,
                 loader: SkillLoader | None = None) -> None:
        self.registry = registry
        self.discovery = discovery
        self.tools = tools
        self.dependencies = dependencies or SkillDependencyManager(tools)
        self.loader = loader or SkillLoader()

    def profile(self, role: str) -> RoleProfile:
        return profile_for(role)

    def assign(self, role: str, goal: str, *, limit: int | None = None,
               budget_tokens: int = 4000) -> Assignment:
        profile = self.profile(role)
        wanted = limit or profile.max_skills
        candidates = self.discovery.for_agent(role, goal, limit=wanted * 3)
        accepted = [match for match in candidates if self._accepts(match.record, role, profile)]
        matches = []
        seen: set[str] = set()
        for match in accepted:
            key = match.record.content_sha256 or f"{match.record.name.casefold()}"
            if key in seen or match.record.name.casefold() in seen:
                continue
            seen.update({key, match.record.name.casefold()})
            matches.append(match)
            if len(matches) >= wanted:
                break
        missing: dict[str, list[str]] = {}
        if self.tools:
            for match in matches:
                absent = self.tools.missing_for(match.record)
                if absent:
                    missing[match.record.skill_id] = absent
        context = self.loader.load(matches, budget_tokens=budget_tokens)
        reason = f"role={role}; mission={goal[:120]}"
        self.registry.assign(role, [match.record.skill_id for match in matches], reason=reason)
        return Assignment(role, goal, matches, context, missing)

    def request(self, requester: str, need: str, *, owner: str | None = None,
                limit: int = 3) -> list[SkillMatch]:
        """Ask another agent for skills that match a need.

        With `owner`, only skills already assigned to that agent are considered,
        and the requester must be allowed to use them.
        """
        requester_profile = self.profile(requester)
        if owner:
            candidates = [(record, reason) for record, reason in self.registry.by_agent(owner)]
            matches: list[SkillMatch] = []
            for record, reason in candidates:
                if not record.is_usable or record.security_status == SecurityDecision.BLOCK:
                    continue
                if not self._accepts(record, requester, requester_profile):
                    continue
                if need and not _relevant(record, need):
                    continue
                matches.append(SkillMatch(record, 1.0, reasons=[f"lent by {owner}: {reason[:80]}"]))
                if len(matches) >= limit:
                    break
        else:
            matches = self.discovery.discover(need, role=requester, limit=limit)
            matches = [match for match in matches if self._accepts(match.record, requester, requester_profile)]
        self.registry.assign(requester, [match.record.skill_id for match in matches],
                             reason=f"requested: {need[:100]}")
        return matches

    def borrow(self, requester: str, owner: str, skill_id: str) -> tuple[bool, str]:
        record = self.registry.get(skill_id)
        if record is None:
            return False, "unknown skill"
        if skill_id not in {record.skill_id for record, _ in self.registry.by_agent(owner)}:
            return False, f"skill is not assigned to {owner}"
        profile = self.profile(requester)
        if not self._accepts(record, requester, profile):
            return False, f"{requester} is not permitted to use this skill"
        self.registry.assign(requester, [skill_id], reason=f"borrowed from {owner}")
        self.registry.record_event(skill_id, "lend", f"{owner} -> {requester}")
        return True, "assigned"

    def check_dependencies(self, skill_id: str) -> list[DependencyStatus]:
        record = self.registry.get(skill_id)
        if record is None:
            raise KeyError(skill_id)
        return self.dependencies.check(record)

    def sync_agent_registry(self, agents: AgentRegistry, goal: str, *,
                            roles: list[str] | None = None,
                            budget_tokens: int = 4000) -> dict[str, Assignment]:
        assignments: dict[str, Assignment] = {}
        for spec in agents.list():
            if roles and spec.name not in roles:
                continue
            try:
                assignment = self.assign(spec.name, goal, limit=spec.max_concurrency * 12,
                                         budget_tokens=budget_tokens)
            except KeyError:
                continue
            spec.skills = [
                Skill(
                    name=match.record.name,
                    description=match.record.description[:280],
                    tool_permissions=frozenset(match.record.permissions),
                )
                for match in assignment.matches
            ]
            assignments[spec.name] = assignment
        return assignments

    def _accepts(self, record: SkillRecord, role: str, profile: RoleProfile) -> bool:
        if record.security_status == SecurityDecision.BLOCK:
            return False
        if record.compatible_agents and role in record.compatible_agents:
            return True
        if record.category in profile.categories:
            return True
        return not record.compatible_agents and not profile.categories


def _relevant(record: SkillRecord, need: str) -> bool:
    tokens = {token for token in need.lower().split() if len(token) > 2}
    haystack = f"{record.name} {record.description} {' '.join(record.tags)}".lower()
    return any(token in haystack for token in tokens)
