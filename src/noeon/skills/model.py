from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any

from pydantic import BaseModel, Field

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


class ValidationStatus(StrEnum):
    UNVALIDATED = "unvalidated"
    VALID = "valid"
    INVALID = "invalid"


class SecurityDecision(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class InstallationStatus(StrEnum):
    DISCOVERED = "discovered"
    IMPORTED = "imported"
    INSTALLED = "installed"
    REFERENCE_ONLY = "reference_only"
    UNINSTALLED = "uninstalled"


class Origin(StrEnum):
    UPSTREAM = "upstream"
    LOCAL = "local"
    GENERATED = "generated"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 10,
    Severity.MEDIUM: 25,
    Severity.HIGH: 50,
    Severity.CRITICAL: 100,
}


class SkillFinding(BaseModel):
    code: str
    severity: Severity
    message: str
    evidence: str = ""
    location: str = ""

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self.severity]


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-.")
    return slug or "skill"


def skill_id_for(repository: str, source_path: str) -> str:
    """Stable identifier derived from provenance, not content.

    Re-importing an updated skill keeps the same id, so assignments, installs and
    audit history survive version changes; the content hash tracks the version.
    """
    rel = source_path
    if rel.endswith("/SKILL.md"):
        rel = rel[: -len("/SKILL.md")]
    elif rel == "SKILL.md":
        rel = ""
    segments = [slugify(part) for part in rel.split("/") if part]
    repo = repository.strip("/").lower()
    return "/".join([repo, *segments]) if segments else repo


class SkillRecord(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)
    source_repository: str = ""
    source_version: str = ""
    source_path: str = ""
    source_url: str = ""
    license: str = "unknown"
    dependencies: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    compatible_agents: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    security_status: SecurityDecision = SecurityDecision.ALLOW
    security_findings: list[SkillFinding] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    quality_score: int = 0
    last_verified: datetime | None = None
    installation_status: InstallationStatus = InstallationStatus.DISCOVERED
    origin: Origin = Origin.UPSTREAM
    content_sha256: str = ""
    size_bytes: int = 0
    duplicate_of: str | None = None
    instructions: str = ""
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_usable(self) -> bool:
        return (
            self.validation_status == ValidationStatus.VALID
            and self.security_status != SecurityDecision.BLOCK
            and self.installation_status
            in {InstallationStatus.IMPORTED, InstallationStatus.INSTALLED}
        )

    @property
    def needs_review(self) -> bool:
        return self.security_status == SecurityDecision.REVIEW

    def set_content(self, text: str) -> str:
        self.content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.size_bytes = len(text.encode("utf-8"))
        return self.content_sha256


class SkillSource(BaseModel):
    repository: str
    ref: str = "main"
    mode: str = "import"
    license: str = "unknown"
    reason: str = ""
    include: list[str] = Field(default_factory=lambda: ["**/SKILL.md"])
    exclude: list[str] = Field(default_factory=list)
    license_file_required: bool = False

    def matches(self, path: str) -> bool:
        if not path.endswith("SKILL.md"):
            return False
        if any(_glob_match(pattern, path) for pattern in self.exclude):
            return False
        return any(_glob_match(pattern, path) for pattern in self.include)


def _glob_match(pattern: str, path: str) -> bool:
    if pattern.startswith("**/"):
        return fnmatch(path, pattern) or fnmatch("/" + path, pattern)
    return fnmatch(path, pattern)


class SourceReport(BaseModel):
    repository: str
    ref: str = ""
    commit: str = ""
    mode: str = "import"
    license: str = "unknown"
    license_source: str = ""
    discovered: int = 0
    imported: int = 0
    validated: int = 0
    blocked: int = 0
    review: int = 0
    duplicates: int = 0
    skipped: int = 0
    notes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
