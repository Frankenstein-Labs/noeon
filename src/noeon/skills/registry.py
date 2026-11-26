from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from .model import InstallationStatus, SkillRecord, ValidationStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    tags TEXT NOT NULL,
    source_repository TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    license TEXT NOT NULL,
    security_status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    installation_status TEXT NOT NULL,
    quality_score INTEGER NOT NULL,
    origin TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duplicate_of TEXT,
    payload TEXT NOT NULL,
    identity_hash TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_validation ON skills(validation_status);
CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source_repository);
CREATE INDEX IF NOT EXISTS idx_skills_hash ON skills(content_sha256);
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    skill_id UNINDEXED, name, description, tags, content, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS skill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_events_skill ON skill_events(skill_id, id);
CREATE TABLE IF NOT EXISTS agent_skills (
    agent_name TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    assigned_at REAL NOT NULL,
    PRIMARY KEY (agent_name, skill_id)
);
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_skills (
    mission_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    score REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (mission_id, skill_id)
);
"""

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+#-]*")


def _identity_hash(record: SkillRecord) -> str:
    stable = record.model_dump(
        mode="json", exclude={"created_at", "updated_at", "last_verified"}
    )
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _fts_query(query: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(query.lower()) if len(token) > 1][:24]
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in dict.fromkeys(tokens))


class SkillRegistry:
    """SQLite-backed skill catalog with full-text search and audit history."""

    def __init__(self, path: str | Path = "~/.noeon/skills.sqlite3") -> None:
        self.path = str(Path(path).expanduser()) if str(path) != ":memory:" else ":memory:"
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript(_SCHEMA)
        try:
            self._connection.execute(
                "ALTER TABLE skills ADD COLUMN identity_hash TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def upsert(self, record: SkillRecord) -> str:
        payload = json.dumps(record.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        identity = _identity_hash(record)
        now = time.time()
        with self._lock:
            existing = self._connection.execute(
                "SELECT identity_hash FROM skills WHERE skill_id=?", (record.skill_id,)
            ).fetchone()
            if existing and existing["identity_hash"] == identity:
                return "unchanged"
            self._connection.execute(
                """
                INSERT INTO skills(skill_id, name, description, category, tags, source_repository,
                    source_version, source_path, license, security_status, validation_status,
                    installation_status, quality_score, origin, content_sha256, size_bytes,
                    duplicate_of, payload, identity_hash, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    name=excluded.name, description=excluded.description, category=excluded.category,
                    tags=excluded.tags, source_repository=excluded.source_repository,
                    source_version=excluded.source_version, source_path=excluded.source_path,
                    license=excluded.license, security_status=excluded.security_status,
                    validation_status=excluded.validation_status,
                    installation_status=excluded.installation_status,
                    quality_score=excluded.quality_score, origin=excluded.origin,
                    content_sha256=excluded.content_sha256, size_bytes=excluded.size_bytes,
                    duplicate_of=excluded.duplicate_of, payload=excluded.payload,
                    identity_hash=excluded.identity_hash, updated_at=excluded.updated_at
                """,
                (
                    record.skill_id, record.name, record.description, record.category,
                    " ".join(record.tags), record.source_repository, record.source_version,
                    record.source_path, record.license, record.security_status.value,
                    record.validation_status.value, record.installation_status.value,
                    record.quality_score, record.origin.value, record.content_sha256,
                    record.size_bytes, record.duplicate_of, payload, identity, now,
                ),
            )
            self._connection.execute("DELETE FROM skills_fts WHERE skill_id=?", (record.skill_id,))
            self._connection.execute(
                "INSERT INTO skills_fts(skill_id, name, description, tags, content) VALUES(?,?,?,?,?)",
                (record.skill_id, record.name, record.description, " ".join(record.tags),
                 record.instructions[:200_000]),
            )
            self._connection.commit()
        self.record_event(record.skill_id, "upsert", f"sha256={record.content_sha256[:12]}")
        return "updated" if existing else "inserted"

    def save(self, records: list[SkillRecord]) -> dict[str, int]:
        counts: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}
        for record in records:
            counts[self.upsert(record)] += 1
        return counts

    def get(self, skill_id: str) -> SkillRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM skills WHERE skill_id=?", (skill_id,)
            ).fetchone()
        return SkillRecord.model_validate_json(row["payload"]) if row else None

    def find_by_name(self, name: str) -> list[SkillRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM skills WHERE lower(name)=lower(?) ORDER BY quality_score DESC",
                (name,),
            ).fetchall()
        return [SkillRecord.model_validate_json(row["payload"]) for row in rows]

    def delete(self, skill_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
            self._connection.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill_id,))
            self._connection.execute("DELETE FROM agent_skills WHERE skill_id=?", (skill_id,))
            self._connection.commit()
        if cursor.rowcount:
            self.record_event(skill_id, "uninstall")
        return bool(cursor.rowcount)

    def set_installation_status(self, skill_id: str, status: InstallationStatus) -> bool:
        record = self.get(skill_id)
        if record is None:
            return False
        record.installation_status = status
        self.upsert(record)
        self.record_event(skill_id, f"installation:{status.value}")
        return True

    def iter_records(
        self,
        *,
        category: str | None = None,
        validation: ValidationStatus | None = ValidationStatus.VALID,
        installation: InstallationStatus | None = None,
    ) -> Iterator[SkillRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category=?")
            params.append(category)
        if validation:
            clauses.append("validation_status=?")
            params.append(validation.value)
        if installation:
            clauses.append("installation_status=?")
            params.append(installation.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            cursor = self._connection.execute(
                f"SELECT payload FROM skills {where} ORDER BY quality_score DESC, skill_id", params
            )
        for row in cursor:
            yield SkillRecord.model_validate_json(row["payload"])

    def all(self, limit: int | None = None) -> list[SkillRecord]:
        query = "SELECT payload FROM skills ORDER BY skill_id"
        if limit:
            query += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._connection.execute(query).fetchall()
        return [SkillRecord.model_validate_json(row["payload"]) for row in rows]

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        categories: list[str] | None = None,
        usable_only: bool = True,
        min_quality: int = 0,
    ) -> list[tuple[SkillRecord, float]]:
        match = _fts_query(query)
        sql = (
            "SELECT s.payload, bm25(skills_fts) AS rank FROM skills_fts "
            "JOIN skills s ON s.skill_id = skills_fts.skill_id WHERE skills_fts MATCH ?"
        )
        params: list[Any] = [match]
        if match:
            if usable_only:
                sql += " AND s.validation_status='valid' AND s.security_status!='block'"
            if categories:
                sql += f" AND s.category IN ({','.join('?' for _ in categories)})"
                params.extend(categories)
            if min_quality:
                sql += " AND s.quality_score>=?"
                params.append(min_quality)
            sql += " ORDER BY rank LIMIT ?"
            params.append(max(limit * 5, 50))
            with self._lock:
                rows = self._connection.execute(sql, params).fetchall()
        else:
            rows = []
        if not rows:
            return self._like_search(query, limit, categories, usable_only, min_quality)
        results: list[tuple[SkillRecord, float]] = []
        for row in rows:
            score = -float(row["rank"])
            results.append((SkillRecord.model_validate_json(row["payload"]), round(score, 6)))
        return results[:limit]

    def _like_search(
        self, query: str, limit: int, categories: list[str] | None,
        usable_only: bool, min_quality: int,
    ) -> list[tuple[SkillRecord, float]]:
        terms = [f"%{token}%" for token in _TOKEN_RE.findall(query.lower())][:6] or ["%%"]
        clauses = ["(lower(name) LIKE ? OR lower(description) LIKE ? OR lower(tags) LIKE ?)"] * len(terms)
        params: list[Any] = []
        for term in terms:
            params.extend([term, term, term])
        sql = f"SELECT payload FROM skills WHERE {' OR '.join(clauses)}"
        if usable_only:
            sql += " AND validation_status='valid' AND security_status!='block'"
        if categories:
            sql += f" AND category IN ({','.join('?' for _ in categories)})"
            params.extend(categories)
        if min_quality:
            sql += " AND quality_score>=?"
            params.append(min_quality)
        sql += " ORDER BY quality_score DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [(SkillRecord.model_validate_json(row["payload"]), 0.5) for row in rows]

    def by_agent(self, agent_name: str) -> list[tuple[SkillRecord, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT s.payload, a.reason FROM agent_skills a JOIN skills s ON s.skill_id=a.skill_id "
                "WHERE a.agent_name=? ORDER BY s.quality_score DESC",
                (agent_name,),
            ).fetchall()
        return [(SkillRecord.model_validate_json(row["payload"]), row["reason"]) for row in rows]

    def assign(self, agent_name: str, skill_ids: list[str], *, reason: str = "") -> int:
        assigned = 0
        with self._lock:
            for skill_id in skill_ids:
                if not self._connection.execute(
                    "SELECT 1 FROM skills WHERE skill_id=?", (skill_id,)
                ).fetchone():
                    continue
                self._connection.execute(
                    "INSERT INTO agent_skills(agent_name, skill_id, reason, assigned_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(agent_name, skill_id) DO UPDATE SET reason=excluded.reason",
                    (agent_name, skill_id, reason, time.time()),
                )
                assigned += 1
            self._connection.commit()
        return assigned

    def unassign(self, agent_name: str, skill_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM agent_skills WHERE agent_name=? AND skill_id=?", (agent_name, skill_id)
            )
            self._connection.commit()
        return bool(cursor.rowcount)

    def record_mission(self, mission_id: str, goal: str, skills: list[tuple[str, float, str]]) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO missions(mission_id, goal, created_at) VALUES(?,?,?)",
                (mission_id, goal, time.time()),
            )
            for skill_id, score, reason in skills:
                self._connection.execute(
                    "INSERT OR REPLACE INTO mission_skills(mission_id, skill_id, score, reason) "
                    "VALUES(?,?,?,?)",
                    (mission_id, skill_id, score, reason),
                )
            self._connection.commit()

    def mission_skills(self, mission_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT skill_id, score, reason FROM mission_skills WHERE mission_id=? "
                "ORDER BY score DESC",
                (mission_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(self, skill_id: str, operation: str, detail: str = "") -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO skill_events(skill_id, operation, detail, created_at) VALUES(?,?,?,?)",
                (skill_id, operation, detail, time.time()),
            )
            self._connection.commit()

    def events(self, skill_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if skill_id:
                rows = self._connection.execute(
                    "SELECT * FROM skill_events WHERE skill_id=? ORDER BY id DESC LIMIT ?",
                    (skill_id, limit),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM skill_events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def duplicates(self) -> list[tuple[str, list[str]]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT content_sha256, group_concat(skill_id) AS ids FROM skills "
                "WHERE content_sha256 != '' GROUP BY content_sha256 HAVING count(*) > 1"
            ).fetchall()
        return [(row["content_sha256"], row["ids"].split(",")) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._connection.execute("SELECT count(*) AS n FROM skills").fetchone()["n"]
            by_category = {
                row["category"]: row["n"]
                for row in self._connection.execute(
                    "SELECT category, count(*) AS n FROM skills GROUP BY category ORDER BY n DESC"
                )
            }
            by_validation = {
                row["validation_status"]: row["n"]
                for row in self._connection.execute(
                    "SELECT validation_status, count(*) AS n FROM skills GROUP BY validation_status"
                )
            }
            by_security = {
                row["security_status"]: row["n"]
                for row in self._connection.execute(
                    "SELECT security_status, count(*) AS n FROM skills GROUP BY security_status"
                )
            }
            by_license = {
                row["license"]: row["n"]
                for row in self._connection.execute(
                    "SELECT license, count(*) AS n FROM skills GROUP BY license ORDER BY n DESC"
                )
            }
            by_source = {
                row["source_repository"]: row["n"]
                for row in self._connection.execute(
                    "SELECT source_repository, count(*) AS n FROM skills "
                    "GROUP BY source_repository ORDER BY n DESC"
                )
            }
            by_installation = {
                row["installation_status"]: row["n"]
                for row in self._connection.execute(
                    "SELECT installation_status, count(*) AS n FROM skills GROUP BY installation_status"
                )
            }
        return {
            "total": total,
            "by_category": by_category,
            "by_validation": by_validation,
            "by_security": by_security,
            "by_license": by_license,
            "by_source": by_source,
            "by_installation": by_installation,
        }

    def export_jsonl(self, path: str | Path, *, include_instructions: bool = False) -> int:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        records = self.all()
        if str(target).endswith(".gz"):
            raw = gzip.GzipFile(filename="", fileobj=target.open("wb"), mode="wb", mtime=0)
            with raw, io.TextIOWrapper(raw, encoding="utf-8") as handle:
                self._write_jsonl(handle, records, include_instructions)
        else:
            with target.open("wt", encoding="utf-8") as handle:
                self._write_jsonl(handle, records, include_instructions)
        return len(records)

    def _write_jsonl(self, handle, records: list[SkillRecord],
                     include_instructions: bool) -> None:
        for record in records:
            payload = record.model_dump(mode="json")
            if not include_instructions:
                payload["instructions"] = ""
                payload["created_at"] = "1970-01-01T00:00:00Z"
                payload["updated_at"] = "1970-01-01T00:00:00Z"
                payload["last_verified"] = None
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")

    def import_jsonl(self, path: str | Path) -> dict[str, int]:
        counts: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}
        target = Path(path)
        opener = gzip.open if str(target).endswith(".gz") else open
        with opener(target, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                counts[self.upsert(SkillRecord.model_validate_json(line))] += 1
        return counts

    def new_mission_id(self) -> str:
        return str(uuid4())
