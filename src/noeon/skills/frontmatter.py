from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

MAX_SKILL_BYTES = 512 * 1024
MAX_FRONTMATTER_BYTES = 64 * 1024


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSkill:
    frontmatter: dict[str, Any]
    body: str
    raw_frontmatter: str


def parse_frontmatter(text: str, *, required: bool = False) -> ParsedSkill:
    if len(text.encode("utf-8")) > MAX_SKILL_BYTES:
        raise FrontmatterError(f"SKILL.md exceeds {MAX_SKILL_BYTES} bytes")
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        if required:
            raise FrontmatterError("SKILL.md must start with a YAML frontmatter block")
        return ParsedSkill({}, normalized, "")

    end = normalized.find("\n---", 4)
    if end == -1:
        raise FrontmatterError("unterminated YAML frontmatter")
    raw = normalized[4:end]
    if len(raw.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise FrontmatterError(f"frontmatter exceeds {MAX_FRONTMATTER_BYTES} bytes")
    body_start = normalized.find("\n", end + 1)
    body = normalized[body_start + 1 :] if body_start != -1 else ""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML frontmatter: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a mapping")
    cleaned = {str(key): value for key, value in data.items()}
    return ParsedSkill(cleaned, body, raw)


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "," in stripped and "\n" not in stripped:
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return [line.strip("- ").strip() for line in stripped.splitlines() if line.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())
