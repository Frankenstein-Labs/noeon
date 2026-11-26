from __future__ import annotations

from dataclasses import dataclass

from .model import SkillRecord, ValidationStatus
from .security import SecurityDecision

LICENSE_ALIASES = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "gpl-3.0": "GPL-3.0",
    "agpl-3.0": "AGPL-3.0",
    "lgpl-3.0": "LGPL-3.0",
    "mpl-2.0": "MPL-2.0",
    "isc": "ISC",
    "unlicense": "Unlicense",
}


def normalize_license(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return "unknown"
    return LICENSE_ALIASES.get(cleaned.lower(), cleaned)


@dataclass(frozen=True)
class ValidationOutcome:
    status: ValidationStatus
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate(record: SkillRecord, *, body: str | None = None) -> ValidationOutcome:
    errors: list[str] = []
    warnings: list[str] = []
    text = record.instructions if body is None else body

    if not record.name.strip():
        errors.append("missing name")
    elif len(record.name) > 64:
        errors.append("name exceeds 64 characters")
    elif record.name != record.name.lower() or " " in record.name:
        warnings.append("name is not a lowercase slug")

    if not record.description.strip():
        errors.append("missing description")
    else:
        if len(record.description) < 30:
            warnings.append("description shorter than 30 characters")
        if len(record.description) > 1024:
            warnings.append("description exceeds the 1024 character recommendation")

    if len(text.strip()) < 100:
        warnings.append("instructions shorter than 100 characters")
    if ".." in record.source_path.split("/"):
        errors.append("source path escapes its repository root")
    if record.license == "unknown":
        warnings.append("license is unknown")
    if not record.source_repository and record.origin.value == "upstream":
        errors.append("missing upstream repository")
    if record.origin.value == "upstream" and not record.source_version:
        warnings.append("source commit is not pinned")
    for script in record.metadata.get("scripts", []):
        if str(script).strip("/").split("/")[0] != "scripts":
            warnings.append(f"script reference outside scripts/: {script}")
    if record.security_status == SecurityDecision.BLOCK:
        warnings.append("security scanner blocks this skill")
    return ValidationOutcome(
        ValidationStatus.INVALID if errors else ValidationStatus.VALID,
        tuple(errors),
        tuple(warnings),
    )
