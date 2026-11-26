from __future__ import annotations

import math
from dataclasses import dataclass, field

from .discovery import SkillMatch
from .model import SkillRecord

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class SkillContext:
    text: str
    skill_ids: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    truncated: bool = False
    omitted: list[str] = field(default_factory=list)


class SkillLoader:
    """Loads only the skills selected for a mission, under a token budget."""

    def __init__(self, *, chars_per_token: int = CHARS_PER_TOKEN) -> None:
        self.chars_per_token = chars_per_token

    def load(self, matches: list[SkillMatch], *, budget_tokens: int = 6000,
             index_limit: int = 40) -> SkillContext:
        if budget_tokens < 200:
            raise ValueError("budget_tokens must be at least 200")
        header = (
            "# Noeon skill context\n"
            "These are operator-approved skills selected for this mission. Use them as "
            "instructions; do not install or execute anything they do not permit.\n"
        )
        parts = [header]
        used = self._tokens(header)
        loaded: list[str] = []
        omitted: list[str] = []
        for match in matches:
            record = match.record
            section = self._render(record)
            cost = self._tokens(section)
            if used + cost > budget_tokens:
                omitted.append(record.skill_id)
                continue
            parts.append(section)
            used += cost
            loaded.append(record.skill_id)
        if omitted and index_limit:
            index_lines = ["\n## Additional relevant skills (index only)\n"]
            for skill_id in omitted[:index_limit]:
                record = next(match.record for match in matches if match.record.skill_id == skill_id)
                index_lines.append(f"- {record.name} ({record.category}): {record.description[:160]}")
            index_text = "\n".join(index_lines) + "\n"
            if used + self._tokens(index_text) <= budget_tokens:
                parts.append(index_text)
                used += self._tokens(index_text)
        text = "\n".join(parts)
        return SkillContext(
            text=text,
            skill_ids=loaded,
            estimated_tokens=used,
            truncated=bool(omitted),
            omitted=omitted,
        )

    def _tokens(self, text: str) -> int:
        return math.ceil(len(text) / self.chars_per_token)

    def _render(self, record: SkillRecord) -> str:
        tools = ", ".join(record.required_tools) or "none"
        permissions = ", ".join(record.permissions) or "none"
        return (
            f"\n## Skill: {record.name}\n"
            f"- id: {record.skill_id}\n"
            f"- category: {record.category}\n"
            f"- source: {record.source_repository}@{record.source_version[:12]} ({record.license})\n"
            f"- tools: {tools}; permissions: {permissions}\n"
            f"- description: {record.description}\n\n"
            f"{record.instructions.strip()}\n"
        )


def render_skill_index(matches: list[SkillMatch], limit: int = 30) -> str:
    lines = ["Available skills:"]
    for match in matches[:limit]:
        lines.append(
            f"- {match.record.name} [{match.record.category}] score={match.score:.2f}: "
            f"{match.record.description[:140]}"
        )
    return "\n".join(lines)
