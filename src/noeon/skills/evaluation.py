from __future__ import annotations

from dataclasses import dataclass, field

from .model import SkillRecord, ValidationStatus


@dataclass(frozen=True)
class ScorePart:
    name: str
    points: int
    maximum: int
    detail: str = ""


@dataclass
class QualityReport:
    score: int
    parts: list[ScorePart] = field(default_factory=list)

    def breakdown(self) -> dict[str, int]:
        return {part.name: part.points for part in self.parts}


def evaluate(record: SkillRecord, *, body: str, allowlisted_source: bool) -> QualityReport:
    """Deterministic rubric, 0-100. No model calls, no invented numbers."""
    parts: list[ScorePart] = []
    frontmatter = record.frontmatter or {}
    description = record.description or ""

    name_points = 5 if record.name else 0
    parts.append(ScorePart("name", name_points, 5))
    description_points = 10 if len(description) >= 40 else 5 if description else 0
    parts.append(ScorePart("description", description_points, 10))
    parts.append(ScorePart("license_declared", 5, 5) if record.license != "unknown"
                 else ScorePart("license_declared", 0, 5))

    trigger_language = any(
        phrase in description.lower()
        for phrase in ("use when", "when to use", "trigger", "use this", "utiliser")
    )
    parts.append(ScorePart("trigger_language", 5 if trigger_language else 0, 5))
    parts.append(ScorePart("description_depth", 5 if len(description) >= 120 else 0, 5))

    headings = sum(1 for line in body.splitlines() if line.lstrip().startswith("#"))
    parts.append(ScorePart("body_length", 10 if len(body) >= 400 else 5 if len(body) >= 150 else 0, 10))
    parts.append(ScorePart("body_structure", 10 if headings >= 3 else 5 if headings else 0, 10))

    scripts = record.metadata.get("scripts", [])
    references = record.metadata.get("references", [])
    parts.append(ScorePart("scripts", 5 if scripts else 0, 5))
    parts.append(ScorePart("references", 5 if references else 0, 5))

    parts.append(ScorePart("pinned_commit", 5 if record.source_version else 0, 5))
    parts.append(ScorePart("curated_source", 5 if allowlisted_source else 0, 5))

    meta = frontmatter.get("metadata") or {}
    parts.append(ScorePart("metadata", 5 if isinstance(meta, dict) and meta else 0, 5))

    base = sum(part.points for part in parts)
    penalty = min(30, record.metadata.get("security_risk", 0) // 2)
    parts.append(ScorePart("security_penalty", -penalty, 0))
    score = max(0, min(100, base - penalty))
    return QualityReport(score=score, parts=parts)


def evaluation_summary(records: list[SkillRecord]) -> dict[str, float | int]:
    usable = [r for r in records if r.validation_status == ValidationStatus.VALID]
    scores = sorted(r.quality_score for r in usable)
    if not scores:
        return {"count": 0, "median": 0, "mean": 0, "p90": 0}
    middle = scores[len(scores) // 2]
    p90 = scores[min(len(scores) - 1, int(len(scores) * 0.9))]
    return {
        "count": len(scores),
        "median": middle,
        "mean": round(sum(scores) / len(scores), 1),
        "p90": p90,
    }
