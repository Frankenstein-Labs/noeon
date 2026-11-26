from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .model import InstallationStatus, SecurityDecision, SkillRecord, ValidationStatus
from .registry import SkillRegistry
from .taxonomy import CATEGORY_AGENTS, RoleProfile, profile_for


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class SkillMatch:
    record: SkillRecord
    score: float
    lexical: float = 0.0
    semantic: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def explain(self) -> dict[str, object]:
        return {
            "skill_id": self.record.skill_id,
            "name": self.record.name,
            "category": self.record.category,
            "score": round(self.score, 4),
            "lexical": round(self.lexical, 4),
            "semantic": round(self.semantic, 4),
            "quality": self.record.quality_score,
            "reasons": self.reasons,
        }


class SkillDiscoveryEngine:
    """Ranked skill selection over the catalog.

    Ranking is lexical (BM25 from SQLite FTS5) plus deterministic boosts, so it
    works with no model provider. An embedding provider can be plugged in for
    semantic similarity; without one, no semantic claim is made.
    """

    def __init__(self, registry: SkillRegistry, *,
                 embeddings: EmbeddingProvider | None = None,
                 vector_path: str | Path | None = None) -> None:
        self.registry = registry
        self.embeddings = embeddings
        self.vector_path = Path(vector_path).expanduser() if vector_path else None
        self._vectors: dict[str, list[float]] = {}
        if self.vector_path and self.vector_path.exists():
            self._load_vectors()

    @property
    def semantic_available(self) -> bool:
        return self.embeddings is not None

    def build_vector_index(self, *, limit: int | None = None) -> int:
        if not self.embeddings:
            raise RuntimeError("no embedding provider configured")
        records = [
            record for record in self.registry.iter_records(
                validation=ValidationStatus.VALID, installation=InstallationStatus.INSTALLED
            )
            if record.security_status != SecurityDecision.BLOCK
        ]
        if limit:
            records = records[:limit]
        if not records:
            return 0
        vectors: dict[str, list[float]] = {}
        batch = 32
        for start in range(0, len(records), batch):
            chunk = records[start : start + batch]
            texts = [f"{record.name}. {record.description} {' '.join(record.tags)}" for record in chunk]
            for record, vector in zip(chunk, self.embeddings.embed(texts), strict=True):
                vectors[record.skill_id] = vector
        self._vectors = vectors
        if self.vector_path:
            self.vector_path.parent.mkdir(parents=True, exist_ok=True)
            with self.vector_path.open("w", encoding="utf-8") as handle:
                for skill_id, vector in sorted(vectors.items()):
                    handle.write(json.dumps({"skill_id": skill_id, "vector": vector}) + "\n")
        return len(vectors)

    def _load_vectors(self) -> None:
        assert self.vector_path is not None
        with self.vector_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                self._vectors[item["skill_id"]] = [float(value) for value in item["vector"]]

    def discover(self, goal: str, *, role: str | None = None, limit: int = 10,
                 categories: list[str] | None = None, usable_only: bool = True,
                 min_quality: int = 0, include_semantic: bool = True) -> list[SkillMatch]:
        profile = profile_for(role) if role else None
        query = " ".join([goal, *(profile.keywords if profile else ())]).strip()
        allowed_categories = list(categories) if categories else None
        if allowed_categories is None and profile:
            allowed_categories = list(profile.categories)
        lexical = self.registry.search(
            query, limit=max(limit * 8, 80), categories=allowed_categories,
            usable_only=usable_only, min_quality=min_quality,
        )
        if not lexical:
            lexical = self.registry.search(query, limit=max(limit * 8, 80), usable_only=usable_only)

        semantic_scores: dict[str, float] = {}
        if include_semantic and self.embeddings and self._vectors:
            query_vector = self.embeddings.embed([query])[0]
            semantic_scores = {
                skill_id: _cosine(query_vector, vector) for skill_id, vector in self._vectors.items()
            }

        matches: list[SkillMatch] = []
        for record, lexical_score in lexical:
            if record.duplicate_of:
                continue
            if usable_only and not record.is_usable:
                continue
            normalized = lexical_score / (lexical_score + 1.0) if lexical_score > 0 else 0.0
            reasons = ["lexical match"]
            score = normalized
            if profile:
                if record.category in profile.categories:
                    score += 0.25
                    reasons.append(f"category {record.category} matches role {profile.name}")
                hits = [keyword for keyword in profile.keywords if keyword in _haystack(record)]
                if hits:
                    score += min(0.2, 0.05 * len(hits))
                    reasons.append(f"role keywords: {', '.join(hits[:3])}")
            if role and role in record.compatible_agents:
                score += 0.1
                reasons.append("declared compatible with role")
            score += (record.quality_score / 100.0) * 0.2
            if record.security_status == SecurityDecision.REVIEW:
                score -= 0.15
                reasons.append("security review required")
            if record.duplicate_of:
                score -= 0.3
            semantic = semantic_scores.get(record.skill_id, 0.0)
            if semantic:
                score = 0.6 * score + 0.4 * semantic
                reasons.append("semantic similarity")
            matches.append(SkillMatch(record, round(score, 6), normalized, round(semantic, 6), reasons))

        if semantic_scores:
            existing = {match.record.skill_id for match in matches}
            for skill_id, similarity in sorted(semantic_scores.items(), key=lambda item: -item[1]):
                if skill_id in existing or similarity < 0.25:
                    continue
                record = self.registry.get(skill_id)
                if record is None or (usable_only and not record.is_usable):
                    continue
                matches.append(SkillMatch(record, round(0.5 * similarity, 6), 0.0,
                                          round(similarity, 6), ["semantic only"]))

        matches.sort(key=lambda match: (-match.score, match.record.skill_id))
        return matches[:limit]

    def for_agent(self, role: str, goal: str, *, limit: int | None = None) -> list[SkillMatch]:
        profile: RoleProfile = profile_for(role)
        return self.discover(goal, role=role, limit=limit or profile.max_skills)

    def categories_for_agents(self) -> dict[str, list[str]]:
        return {agent: categories for agent, categories in CATEGORY_AGENTS.items()}


def _haystack(record: SkillRecord) -> str:
    return f"{record.name} {record.description} {' '.join(record.tags)}".lower()


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def query_terms(text: str) -> Counter[str]:
    return Counter(token.lower() for token in text.split() if len(token) > 2)
