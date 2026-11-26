from __future__ import annotations

import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .manifest import build_record
from .model import (
    InstallationStatus,
    Origin,
    SecurityDecision,
    SkillRecord,
    SkillSource,
    SourceReport,
    ValidationStatus,
    slugify,
)
from .registry import SkillRegistry
from .security import SecurityDecision as _SecurityDecision
from .security import scan_skill
from .sources import GitHubClient, LicenseInfo, SourceFetchError


@dataclass
class InstallResult:
    skill_id: str
    installed: bool
    reason: str = ""
    files: list[str] | None = None


class SkillSyncEngine:
    """Imports upstream SKILL.md files into the registry at pinned commits."""

    def __init__(self, registry: SkillRegistry, *, client: GitHubClient | None = None,
                 cache_dir: str | Path | None = None, max_workers: int = 16) -> None:
        self.registry = registry
        self.client = client or GitHubClient(cache_dir=cache_dir)
        self.max_workers = max_workers
        self.skill_root = Path(cache_dir).expanduser().parent / "skills" if cache_dir else Path(".noeon/skills")

    def sync(self, sources: list[SkillSource], *, only: list[str] | None = None,
             limit_per_source: int | None = None, include_reference: bool = False) -> list[SourceReport]:
        selected = [source for source in sources
                    if not only or source.repository in only]
        reports = [self._sync_source(source, limit_per_source, include_reference) for source in selected]
        self.mark_duplicates()
        duplicate_counts: dict[str, int] = {}
        for record in self.registry.all():
            if record.duplicate_of:
                duplicate_counts[record.source_repository] = (
                    duplicate_counts.get(record.source_repository, 0) + 1
                )
        for report in reports:
            report.duplicates = duplicate_counts.get(report.repository, 0)
        return reports

    def _sync_source(self, source: SkillSource, limit: int | None,
                     include_reference: bool) -> SourceReport:
        report = SourceReport(repository=source.repository, ref=source.ref, mode=source.mode,
                              license=source.license)
        try:
            commit = self.client.resolve_commit(source.repository, source.ref)
            report.commit = commit
            entries = self.client.tree(source.repository, commit,
                                       walk_truncated=source.mode == "import")
            license_info = self.client.license_info(source.repository, entries)
            report.license = _effective_license(source, license_info)
            report.license_source = license_info.source
            paths = [entry.path for entry in entries if source.matches(entry.path)]
            report.discovered = len(paths)
            if source.mode == "reference" and (
                source.repository, commit
            ) in getattr(self.client, "truncated_trees", set()):
                report.notes.append("tree truncated by GitHub; discovered count is a lower bound")
            if limit:
                paths = paths[:limit]
            if source.mode == "reference" and not include_reference:
                report.skipped = len(paths)
                report.notes.append("reference-only source: counted, not imported")
                return report
            if source.license_file_required and not _license_is_clear(report.license):
                report.skipped = len(paths)
                report.notes.append(f"license gate: {report.license or 'unknown'}")
                return report
            if source.mode == "reference":
                for path in paths:
                    record = SkillRecord(
                        skill_id=f"{source.repository.lower()}/{slugify(path.removesuffix('/SKILL.md'))}",
                        name=Path(path).parent.name or "skill",
                        description="Upstream skill referenced but not imported",
                        source_repository=source.repository,
                        source_version=commit,
                        source_path=path,
                        source_url=f"https://github.com/{source.repository}/blob/{commit}/{path}",
                        license=report.license,
                        installation_status=InstallationStatus.REFERENCE_ONLY,
                    )
                    self.registry.upsert(record)
                    report.skipped += 1
                return report
            self._import_paths(source, commit, paths, report)
        except SourceFetchError as exc:
            report.errors.append(str(exc))
        return report

    def _import_paths(self, source: SkillSource, commit: str, paths: list[str],
                      report: SourceReport) -> None:
        def fetch(path: str) -> tuple[str, str | None, str | None]:
            try:
                return path, self.client.raw(source.repository, commit, path), None
            except SourceFetchError as exc:
                return path, None, str(exc)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(fetch, path) for path in paths]
            for future in as_completed(futures):
                path, text, error = future.result()
                if error or text is None:
                    report.skipped += 1
                    if len(report.errors) < 5:
                        report.errors.append(f"{path}: {error}")
                    continue
                try:
                    built = build_record(
                        repository=source.repository, commit=commit, path=path, text=text,
                        declared_license=report.license, allowlisted=True,
                    )
                except Exception as exc:  # noqa: BLE001 - one malformed skill must not stop a sync
                    report.skipped += 1
                    if len(report.errors) < 5:
                        report.errors.append(f"{path}: {type(exc).__name__}: {exc}")
                    continue
                self.registry.upsert(built.record)
                report.imported += 1
                if built.record.validation_status == ValidationStatus.VALID:
                    report.validated += 1
                if built.record.security_status == SecurityDecision.BLOCK:
                    report.blocked += 1
                elif built.record.security_status == SecurityDecision.REVIEW:
                    report.review += 1

    def mark_duplicates(self) -> int:
        marked = 0
        for _digest, skill_ids in self.registry.duplicates():
            records = [(self.registry.get(skill_id), skill_id) for skill_id in skill_ids]
            usable = [(record, skill_id) for record, skill_id in records if record]
            if len(usable) < 2:
                continue
            usable.sort(key=lambda item: (-item[0].quality_score, item[1]))
            keeper = usable[0][1]
            for record, skill_id in usable[1:]:
                if record.duplicate_of != keeper:
                    record.duplicate_of = keeper
                    record.metadata["duplicate_of"] = keeper
                    self.registry.upsert(record)
                    marked += 1
        return marked

    def ingest_local(self, root: str | Path, *, repository: str, license: str = "unknown",
                     commit: str = "local") -> SourceReport:
        root_path = Path(root).expanduser().resolve()
        report = SourceReport(repository=repository, ref=commit, mode="local",
                              license=license, commit=commit)
        for path in sorted(root_path.rglob("SKILL.md")):
            relative = path.relative_to(root_path).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            built = build_record(repository=repository, commit=commit, path=relative, text=text,
                                 declared_license=license, origin=Origin.LOCAL)
            try:
                local_path = path.relative_to(Path.cwd()).as_posix()
            except ValueError:
                local_path = str(path)
            built.record.metadata["local_path"] = local_path
            self.registry.upsert(built.record)
            report.discovered += 1
            report.imported += 1
            if built.record.validation_status == ValidationStatus.VALID:
                report.validated += 1
            if built.record.security_status == SecurityDecision.BLOCK:
                report.blocked += 1
            elif built.record.security_status == SecurityDecision.REVIEW:
                report.review += 1
        return report

    def install(self, skill_id: str, *, force: bool = False) -> InstallResult:
        record = self.registry.get(skill_id)
        if record is None:
            return InstallResult(skill_id, False, "unknown skill")
        if record.security_status == SecurityDecision.BLOCK and not force:
            return InstallResult(skill_id, False, "blocked by security scanner")
        if record.origin.value == "upstream" and record.license == "unknown" and not force:
            return InstallResult(skill_id, False, "license is unknown; refusing to install third-party content")
        if record.validation_status != ValidationStatus.VALID:
            return InstallResult(skill_id, False, "skill is not valid")

        text = record.instructions
        if record.origin.value == "upstream":
            try:
                text = self.client.raw(record.source_repository, record.source_version, record.source_path)
            except SourceFetchError as exc:
                return InstallResult(skill_id, False, f"fetch failed: {exc}")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if record.content_sha256 and digest != record.content_sha256:
                return InstallResult(skill_id, False, "upstream content changed; re-run sync")

        scripts: dict[str, str] = {}
        if record.origin.value == "local":
            base = Path(str(record.metadata.get("local_path", ""))).parent
            for script in record.metadata.get("scripts", [])[:8]:
                candidate = base / script
                if candidate.is_file():
                    try:
                        scripts[script] = candidate.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
        if record.origin.value == "upstream":
            for script in record.metadata.get("scripts", [])[:8]:
                try:
                    scripts[script] = self.client.raw(
                        record.source_repository, record.source_version, script, max_bytes=256 * 1024
                    )
                except SourceFetchError:
                    continue
        report = scan_skill(text, scripts)
        if report.decision == _SecurityDecision.BLOCK and not force:
            record.security_status = report.decision
            record.security_findings = report.findings
            self.registry.upsert(record)
            return InstallResult(skill_id, False, "script scan blocked installation")

        target = self.skill_root / slugify(skill_id.replace("/", "-"))
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(text, encoding="utf-8")
        written = [str(target / "SKILL.md")]
        for script, content in scripts.items():
            destination = target / script
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            written.append(str(destination))
        record.instructions = text
        record.installation_status = InstallationStatus.INSTALLED
        record.last_verified = datetime.now(UTC)
        self.registry.upsert(record)
        self.registry.record_event(skill_id, "install", f"{len(written)} file(s)")
        return InstallResult(skill_id, True, files=written)

    def uninstall(self, skill_id: str) -> bool:
        target = self.skill_root / slugify(skill_id.replace("/", "-"))
        removed = False
        if target.exists():
            shutil.rmtree(target)
            removed = True
        changed = self.registry.set_installation_status(skill_id, InstallationStatus.UNINSTALLED)
        self.registry.record_event(skill_id, "uninstall")
        return removed or changed

    def verify(self, skill_id: str) -> bool:
        record = self.registry.get(skill_id)
        if record is None:
            return False
        if record.origin.value == "generated":
            digest = hashlib.sha256(record.instructions.encode("utf-8")).hexdigest()
            return digest == record.content_sha256
        if record.origin.value == "local":
            candidate = Path(str(record.metadata.get("local_path", "")))
            if not candidate.is_file():
                return False
            text = candidate.read_text(encoding="utf-8", errors="replace")
            verified = hashlib.sha256(text.encode("utf-8")).hexdigest() == record.content_sha256
            if verified:
                record.instructions = text
                record.last_verified = datetime.now(UTC)
                self.registry.upsert(record)
                self.registry.record_event(skill_id, "verify", "local content hash matched")
            return verified
        try:
            text = self.client.raw(record.source_repository, record.source_version, record.source_path)
        except SourceFetchError:
            return False
        verified = hashlib.sha256(text.encode("utf-8")).hexdigest() == record.content_sha256
        if verified:
            record.last_verified = datetime.now(UTC)
            self.registry.upsert(record)
            self.registry.record_event(skill_id, "verify", "content hash matched")
        return verified


def _license_is_clear(license_value: str) -> bool:
    return license_value not in {"", "unknown", "NOASSERTION", "OTHER"}


def _effective_license(source: SkillSource, info: LicenseInfo) -> str:
    if _license_is_clear(info.spdx):
        return info.spdx
    if _license_is_clear(source.license):
        return source.license
    if info.source == "license-file-present":
        return "see-license-file"
    return "unknown"
