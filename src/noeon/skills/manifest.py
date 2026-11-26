from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .evaluation import evaluate
from .frontmatter import FrontmatterError, as_string_list, as_text, parse_frontmatter
from .model import (
    InstallationStatus,
    Origin,
    SecurityDecision,
    SkillRecord,
    ValidationStatus,
    skill_id_for,
)
from .security import scan_skill
from .taxonomy import CATEGORIES, agents_for_category, classify, keyword_tags
from .validate import normalize_license, validate

_SCRIPT_REF_RE = re.compile(r"(?:^|[\s(`'\"])((?:\./)?(?:scripts|references|assets)/[A-Za-z0-9._/-]+)")
_TOOL_PERMISSIONS = {
    "bash": "execute",
    "terminal": "execute",
    "execute": "execute",
    "read": "read",
    "glob": "read",
    "grep": "read",
    "write": "write",
    "edit": "write",
    "str_replace": "write",
    "webfetch": "network",
    "websearch": "network",
    "browser": "network",
    "fetch": "network",
    "task": "execute",
    "mcp": "mcp",
}


@dataclass
class BuiltSkill:
    record: SkillRecord
    frontmatter: dict[str, Any]
    body: str
    error: str | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def permissions_from_tools(tools: list[str]) -> list[str]:
    permissions: set[str] = set()
    for tool in tools:
        base = re.split(r"[(:]", tool.strip().lower(), maxsplit=1)[0].strip()
        for key, permission in _TOOL_PERMISSIONS.items():
            if base == key or base.endswith("/" + key) or base.startswith(key + "__"):
                permissions.add(permission)
    return sorted(permissions)


def _extract_paths(body: str) -> tuple[list[str], list[str]]:
    scripts: set[str] = set()
    references: set[str] = set()
    for match in _SCRIPT_REF_RE.finditer(body):
        path = match.group(1).lstrip("./")
        if path.startswith("scripts/"):
            scripts.add(path)
        elif path.startswith("references/"):
            references.add(path)
    return sorted(scripts)[:32], sorted(references)[:64]


def build_record(
    *,
    repository: str,
    commit: str,
    path: str,
    text: str,
    declared_license: str = "unknown",
    allowlisted: bool = True,
    installation: InstallationStatus = InstallationStatus.IMPORTED,
    origin: Origin = Origin.UPSTREAM,
) -> BuiltSkill:
    skill_id = skill_id_for(repository, path)
    try:
        parsed = parse_frontmatter(text, required=True)
    except FrontmatterError as exc:
        record = SkillRecord(
            skill_id=skill_id, name=Path(path).parent.name or "skill",
            description="", source_repository=repository, source_version=commit,
            source_path=path, license=normalize_license(declared_license),
            installation_status=installation, origin=origin,
            validation_status=ValidationStatus.INVALID,
            validation_errors=[str(exc)],
        )
        record.set_content(text)
        return BuiltSkill(record, {}, text, error=str(exc))

    frontmatter = parsed.frontmatter
    body = parsed.body
    name = as_text(frontmatter.get("name")) or Path(path).parent.name or "skill"
    description = as_text(frontmatter.get("description"))
    category_hint = as_text(frontmatter.get("category")).lower()
    category, taxonomy_tags, _ = classify(name, description, body)
    if category_hint in CATEGORIES:
        category = category_hint

    raw_tools = as_string_list(
        frontmatter.get("allowed-tools")
        or frontmatter.get("allowed_tools")
        or frontmatter.get("tools")
        or frontmatter.get("required-tools")
    )
    required_tools = _canonical_tools(raw_tools)
    explicit_permissions = as_string_list(frontmatter.get("permissions"))
    permissions = sorted(set(explicit_permissions) | set(permissions_from_tools(raw_tools)))

    declared_tags = as_string_list(frontmatter.get("tags"))
    tags = list(dict.fromkeys(
        [*declared_tags, *taxonomy_tags, *keyword_tags(f"{name} {description}"), category]
    ))[:12]

    license_value = as_text(frontmatter.get("license")) or normalize_license(declared_license)
    license_notice = ""
    if license_value and "license.txt" in license_value.lower():
        license_notice = license_value
        license_value = normalize_license(declared_license)
    license_value = normalize_license(license_value)

    meta_block = frontmatter.get("metadata")
    meta_block = meta_block if isinstance(meta_block, dict) else {}
    dependencies = as_string_list(
        frontmatter.get("dependencies") or meta_block.get("dependencies")
    )[:32]

    declared_agents = as_string_list(
        frontmatter.get("compatible_agents") or frontmatter.get("agents")
    )
    compatible_agents = list(dict.fromkeys([*declared_agents, *agents_for_category(category)]))

    scripts, references = _extract_paths(body)
    scripts = list(dict.fromkeys([*as_string_list(frontmatter.get("scripts")), *scripts]))[:32]

    metadata: dict[str, Any] = {
        "scripts": scripts,
        "references": references,
        "raw_tools": raw_tools,
        "license_notice": license_notice,
        "frontmatter_keys": sorted(frontmatter),
    }
    record = SkillRecord(
        skill_id=skill_id,
        name=name,
        description=description,
        category=category,
        tags=tags,
        source_repository=repository,
        source_version=commit,
        source_path=path,
        source_url=(
            f"https://github.com/{repository}/blob/{commit}/{path}" if repository and commit else ""
        ),
        license=license_value,
        dependencies=dependencies,
        required_tools=required_tools,
        compatible_agents=compatible_agents,
        permissions=permissions,
        installation_status=installation,
        origin=origin,
        instructions=body,
        frontmatter=_json_safe(frontmatter),
        metadata=metadata,
    )
    record.set_content(text)

    report = scan_skill(body)
    record.security_status = report.decision
    record.security_findings = report.findings
    metadata["security_risk"] = report.risk_score
    metadata["network_endpoints"] = report.urls[:32]

    outcome = validate(record, body=body)
    record.validation_status = outcome.status
    record.validation_errors = list(outcome.errors)
    record.validation_warnings = list(outcome.warnings)

    quality = evaluate(record, body=body, allowlisted_source=allowlisted)
    record.quality_score = quality.score
    metadata["quality_breakdown"] = quality.breakdown()
    if record.security_status == SecurityDecision.BLOCK:
        metadata["install_blocked"] = True
    record.last_verified = datetime.now(UTC)
    record.updated_at = record.last_verified
    return BuiltSkill(record, frontmatter, body)


def _canonical_tools(tools: list[str]) -> list[str]:
    canonical: list[str] = []
    mapping = {
        "bash": "terminal", "terminal": "terminal", "execute": "terminal",
        "read": "file_editor", "write": "file_editor", "edit": "file_editor",
        "glob": "file_editor", "grep": "file_editor",
        "webfetch": "browser", "websearch": "browser", "browser": "browser",
        "task": "task_tracker", "mcp": "mcp",
    }
    for tool in tools:
        base = re.split(r"[(:]", tool.strip().lower(), maxsplit=1)[0].strip()
        base = base.removeprefix("mcp__")
        mapped = mapping.get(base)
        if mapped and mapped not in canonical:
            canonical.append(mapped)
    return canonical


def record_to_json_line(record: SkillRecord) -> str:
    payload = record.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
