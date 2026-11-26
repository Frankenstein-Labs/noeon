from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_TREE_ENTRIES = 60_000


class SourceFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class TreeEntry:
    path: str
    size: int = 0


@dataclass(frozen=True)
class LicenseInfo:
    spdx: str
    source: str
    path: str = ""


class GitHubClient:
    """Small read-only GitHub client with an optional disk cache.

    `raw` content is cached by commit sha, so a pinned import is reproducible and
    repeat runs do not re-download third-party files.
    """

    def __init__(self, token: str | None = None, *, cache_dir: str | Path | None = None,
                 timeout: int = 45) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN") or ""
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self.timeout = timeout
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Any] = {}
        self.truncated_trees: set[tuple[str, str]] = set()

    def _request(self, url: str, *, accept: str = "application/vnd.github+json") -> bytes:
        request = urllib.request.Request(url, headers={
            "Accept": accept,
            "User-Agent": "noeon-skill-sync",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise SourceFetchError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise SourceFetchError(f"network error for {url}: {exc.reason}") from exc

    def _api_json(self, path: str) -> Any:
        if path in self._cache:
            return self._cache[path]
        data = json.loads(self._request(f"{API_ROOT}{path}"))
        self._cache[path] = data
        return data

    def repo(self, repository: str) -> dict[str, Any]:
        return self._api_json(f"/repos/{repository}")

    def resolve_commit(self, repository: str, ref: str) -> str:
        if _COMMIT_RE.match(ref):
            return ref
        data = self._api_json(f"/repos/{repository}/commits/{ref}")
        return str(data["sha"])

    def tree(self, repository: str, commit: str, *, walk_truncated: bool = True) -> list[TreeEntry]:
        key = f"/repos/{repository}/git/trees/{commit}?recursive=1"
        data = self._api_json(key)
        entries: list[TreeEntry] = []
        if data.get("truncated"):
            self.truncated_trees.add((repository, commit))
        if data.get("truncated") and not walk_truncated:
            entries = [
                TreeEntry(item["path"], item.get("size", 0))
                for item in data.get("tree", [])
                if item["type"] == "blob"
            ]
        elif data.get("truncated"):
            entries = self._walk_trees(repository, commit)
        else:
            entries = [
                TreeEntry(item["path"], item.get("size", 0))
                for item in data.get("tree", [])
                if item["type"] == "blob"
            ]
        if len(entries) > MAX_TREE_ENTRIES:
            raise SourceFetchError(
                f"{repository}@{commit[:8]} exposes {len(entries)} files; refusing to index"
            )
        return entries

    def _walk_trees(self, repository: str, commit: str) -> list[TreeEntry]:
        """Breadth-first fallback for repositories whose recursive tree is truncated."""
        pending: list[tuple[str, str]] = [(commit, "")]
        entries: list[TreeEntry] = []
        seen: set[str] = set()
        while pending:
            sha, prefix = pending.pop(0)
            if sha in seen:
                continue
            seen.add(sha)
            data = self._api_json(f"/repos/{repository}/git/trees/{sha}")
            for item in data.get("tree", []):
                path = f"{prefix}{item['path']}"
                if item["type"] == "blob":
                    entries.append(TreeEntry(path, item.get("size", 0)))
                elif item["type"] == "tree" and item["path"] != "node_modules":
                    pending.append((item["sha"], f"{path}/"))
            if len(entries) > MAX_TREE_ENTRIES:
                return entries
        return entries

    def raw(self, repository: str, commit: str, path: str, *, max_bytes: int = 512 * 1024) -> str:
        cache_path = None
        if self.cache_dir:
            key = hashlib.sha256(f"{repository}@{commit}/{path}".encode()).hexdigest()
            cache_path = self.cache_dir / key[:2] / f"{key}.txt"
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8", errors="replace")
        url = f"{RAW_ROOT}/{repository}/{commit}/{urllib.request.quote(path)}"
        raw = self._request(url, accept="text/plain")
        if len(raw) > max_bytes:
            raise SourceFetchError(f"{path} exceeds {max_bytes} bytes")
        text = raw.decode("utf-8", errors="replace")
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        return text

    def license_info(self, repository: str, entries: list[TreeEntry] | None = None) -> LicenseInfo:
        try:
            data = self.repo(repository)
            license_data = data.get("license") or {}
            spdx = license_data.get("spdx_id") or ""
            if spdx and spdx not in {"NOASSERTION", "OTHER"}:
                return LicenseInfo(spdx, "repository-api", license_data.get("name", ""))
        except SourceFetchError:
            pass
        for entry in entries or []:
            name = entry.path.lower()
            if name in {"license", "license.txt", "license.md", "copying", "copying.txt"}:
                return LicenseInfo("", "license-file-present", entry.path)
        return LicenseInfo("unknown", "none")


def read_sources(path: str | Path) -> list[dict[str, Any]]:
    import tomllib

    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    sources = []
    for item in data.get("sources", []):
        item = dict(item)
        item.setdefault("include", ["**/SKILL.md"])
        sources.append(item)
    return sources


def write_lock(path: str | Path, reports: list[dict[str, Any]], *,
               export: str | Path | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": sorted(reports, key=lambda item: item["repository"]),
        "totals": {
            key: sum(int(report.get(key, 0)) for report in reports)
            for key in ("discovered", "imported", "validated", "blocked", "review", "duplicates", "skipped")
        },
    }
    if export is not None:
        exported = Path(export)
        if exported.is_file():
            payload["export"] = {
                "path": exported.name,
                "sha256": hashlib.sha256(exported.read_bytes()).hexdigest(),
                "bytes": exported.stat().st_size,
            }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
