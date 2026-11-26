from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MemoryConflict(RuntimeError):
    def __init__(self, namespace: str, key: str, expected: int | None, actual: int | None) -> None:
        super().__init__(f"memory conflict for {namespace}/{key}: expected {expected}, actual {actual}")
        self.namespace, self.key, self.expected, self.actual = namespace, key, expected, actual


class MemoryPermissionError(PermissionError):
    pass


@dataclass(frozen=True)
class MemoryEntry:
    namespace: str
    key: str
    value: Any
    version: int
    updated_at: float


class SharedMemory:
    """Persistent shared memory for agents, backed by SQLite WAL.

    Values are JSON documents. Writes use compare-and-swap versions so concurrent
    agents cannot silently overwrite each other. A scope restricts an agent to a
    namespace prefix and optionally makes it read-only.
    """

    def __init__(self, path: str | Path = "~/.noeon/memory.sqlite3") -> None:
        self.path = str(Path(path).expanduser()) if path != ":memory:" else path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (namespace, key)
            );
            CREATE TABLE IF NOT EXISTS memory_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                operation TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at REAL NOT NULL,
                value TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memory_events_scope
                ON memory_events(namespace, key, id);
            """
        )
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def scope(self, namespace_prefix: str, *, writable: bool = True) -> MemoryScope:
        if not namespace_prefix or namespace_prefix.endswith("/"):
            raise ValueError("namespace_prefix must be non-empty and not end with '/'")
        return MemoryScope(self, namespace_prefix, writable=writable)

    async def get(self, namespace: str, key: str) -> MemoryEntry | None:
        return await asyncio.to_thread(self._get_sync, namespace, key)

    async def put(self, namespace: str, key: str, value: Any, *, expected_version: int | None = None) -> MemoryEntry:
        return await asyncio.to_thread(self._put_sync, namespace, key, value, expected_version)

    async def delete(self, namespace: str, key: str, *, expected_version: int | None = None) -> bool:
        return await asyncio.to_thread(self._delete_sync, namespace, key, expected_version)

    async def list(self, namespace: str, *, prefix: str = "") -> list[MemoryEntry]:
        return await asyncio.to_thread(self._list_sync, namespace, prefix)

    async def events(self, namespace: str, key: str, *, after_id: int = 0) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._events_sync, namespace, key, after_id)

    def _get_sync(self, namespace: str, key: str) -> MemoryEntry | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM memory WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
        return self._entry(row) if row else None

    def _put_sync(self, namespace: str, key: str, value: Any, expected_version: int | None) -> MemoryEntry:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        with self._lock:
            row = self._connection.execute(
                "SELECT version FROM memory WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
            actual = int(row["version"]) if row else None
            if expected_version is not None and actual != expected_version:
                raise MemoryConflict(namespace, key, expected_version, actual)
            version = (actual or 0) + 1
            self._connection.execute(
                "INSERT INTO memory(namespace,key,value,version,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value, version=excluded.version, updated_at=excluded.updated_at",
                (namespace, key, encoded, version, now),
            )
            self._connection.execute(
                "INSERT INTO memory_events(namespace,key,operation,version,created_at,value) VALUES(?,?,?,?,?,?)",
                (namespace, key, "put", version, now, encoded),
            )
            self._connection.commit()
        return MemoryEntry(namespace, key, value, version, now)

    def _delete_sync(self, namespace: str, key: str, expected_version: int | None) -> bool:
        now = time.time()
        with self._lock:
            row = self._connection.execute(
                "SELECT version FROM memory WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
            actual = int(row["version"]) if row else None
            if expected_version is not None and actual != expected_version:
                raise MemoryConflict(namespace, key, expected_version, actual)
            if row is None:
                return False
            version = actual + 1
            self._connection.execute("DELETE FROM memory WHERE namespace=? AND key=?", (namespace, key))
            self._connection.execute(
                "INSERT INTO memory_events(namespace,key,operation,version,created_at) VALUES(?,?,?,?,?)",
                (namespace, key, "delete", version, now),
            )
            self._connection.commit()
            return True

    def _list_sync(self, namespace: str, prefix: str) -> list[MemoryEntry]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory WHERE namespace=? AND key LIKE ? ORDER BY key",
                (namespace, f"{prefix}%"),
            ).fetchall()
        return [self._entry(row) for row in rows]

    def _events_sync(self, namespace: str, key: str, after_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM memory_events WHERE namespace=? AND key=? AND id>? ORDER BY id",
                (namespace, key, after_id),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(row["namespace"], row["key"], json.loads(row["value"]),
                           int(row["version"]), float(row["updated_at"]))


class MemoryScope:
    def __init__(self, memory: SharedMemory, namespace_prefix: str, *, writable: bool) -> None:
        self._memory = memory
        self.namespace_prefix = namespace_prefix
        self.writable = writable

    def _namespace(self, namespace: str) -> str:
        if namespace == self.namespace_prefix or namespace.startswith(self.namespace_prefix + "/"):
            return namespace
        raise MemoryPermissionError(f"namespace outside scope: {namespace}")

    async def get(self, namespace: str, key: str) -> MemoryEntry | None:
        return await self._memory.get(self._namespace(namespace), key)

    async def put(self, namespace: str, key: str, value: Any, *, expected_version: int | None = None) -> MemoryEntry:
        if not self.writable:
            raise MemoryPermissionError("memory scope is read-only")
        return await self._memory.put(self._namespace(namespace), key, value,
                                      expected_version=expected_version)

    async def list(self, namespace: str, *, prefix: str = "") -> list[MemoryEntry]:
        return await self._memory.list(self._namespace(namespace), prefix=prefix)
