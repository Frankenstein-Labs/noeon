from __future__ import annotations

import json
from pathlib import Path

from skill_helpers import new_registry, skill_text, write_skill

from noeon.skills import InstallationStatus, SkillSyncEngine, ValidationStatus, build_record
from noeon.skills.registry import SkillRegistry


def test_local_ingest_builds_traceable_records(tmp_path: Path) -> None:
    source = tmp_path / "upstream"
    write_skill(source, "react-forms/SKILL.md", skill_text(
        "react-forms",
        "Build accessible React forms with validation. Use when a React app needs forms.",
        license="MIT",
        body="# React forms\n\n## When to use\n\nUse when a form needs validation.\n\n"
             "## Workflow\n\n1. Define a schema.\n2. Build the component.\n3. Add tests.\n",
    ))
    registry = new_registry(tmp_path)
    try:
        report = SkillSyncEngine(registry).ingest_local(source, repository="acme/skills", license="MIT")
        assert report.imported == 1
        record = registry.get("acme/skills/react-forms")
        assert record is not None
        assert record.validation_status == ValidationStatus.VALID
        assert record.content_sha256
        assert record.license == "MIT"
        assert record.source_repository == "acme/skills"
        assert record.source_url.startswith("https://github.com/acme/skills/")
        assert "react" in record.tags
        assert record.quality_score > 40
    finally:
        registry.close()


def test_invalid_skill_without_frontmatter_is_rejected(tmp_path: Path) -> None:
    record = build_record(
        repository="acme/skills", commit="abc", path="broken/SKILL.md",
        text="# No frontmatter\n\nJust text.",
    ).record
    assert record.validation_status == ValidationStatus.INVALID
    assert any("frontmatter" in error for error in record.validation_errors)


def test_duplicate_detection_marks_one_copy(tmp_path: Path) -> None:
    text = skill_text("shared-skill", "A duplicated skill used to test duplicate detection.")
    source = tmp_path / "upstream"
    write_skill(source, "a/SKILL.md", text)
    write_skill(source, "b/SKILL.md", text)
    registry = new_registry(tmp_path)
    try:
        engine = SkillSyncEngine(registry)
        engine.ingest_local(source, repository="acme/skills", license="MIT")
        assert engine.mark_duplicates() == 1
        records = registry.all()
        assert len(records) == 2
        assert sum(1 for record in records if record.duplicate_of) == 1
        duplicate = next(record for record in records if record.duplicate_of)
        assert duplicate.duplicate_of in {record.skill_id for record in records}
    finally:
        registry.close()


def test_export_import_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "upstream"
    write_skill(source, "one/SKILL.md", skill_text("one", "First skill for the export test."))
    write_skill(source, "two/SKILL.md", skill_text("two", "Second skill for the export test."))
    registry = new_registry(tmp_path)
    exported = tmp_path / "registry.jsonl"
    try:
        SkillSyncEngine(registry).ingest_local(source, repository="acme/skills", license="MIT")
        count = registry.export_jsonl(exported)
        lines = [json.loads(line) for line in exported.read_text().splitlines()]
        assert count == len(lines) == 2
        assert all("instructions" in line for line in lines)
    finally:
        registry.close()

    other = SkillRegistry(tmp_path / "other.sqlite3")
    try:
        counts = other.import_jsonl(exported)
        assert counts["inserted"] == 2
        assert other.get("acme/skills/one") is not None
        assert other.stats()["total"] == 2
    finally:
        other.close()


def test_registry_search_ranks_and_filters(tmp_path: Path) -> None:
    records = []
    for name, description in [
        ("postgres-migrations", "Plan PostgreSQL migrations with rollback. Use when changing SQL schemas."),
        ("react-animations", "Animate React interfaces with motion. Use when adding UI animation."),
    ]:
        records.append(build_record(
            repository="acme/skills", commit="abc", path=f"{name}/SKILL.md",
            text=skill_text(name, description, license="MIT"),
        ).record)
    registry = new_registry(tmp_path)
    try:
        for record in records:
            registry.upsert(record)
        results = registry.search("postgres migration rollback")
        assert results
        assert results[0][0].name == "postgres-migrations"
        assert all(record.validation_status == ValidationStatus.VALID for record, _ in results)
    finally:
        registry.close()


def test_installation_status_is_tracked(tmp_path: Path) -> None:
    source = tmp_path / "upstream"
    write_skill(source, "one/SKILL.md", skill_text("one", "A skill used for status tracking."))
    registry = new_registry(tmp_path)
    try:
        SkillSyncEngine(registry).ingest_local(source, repository="acme/skills", license="MIT")
        assert registry.get("acme/skills/one").installation_status == InstallationStatus.IMPORTED
        registry.set_installation_status("acme/skills/one", InstallationStatus.INSTALLED)
        assert registry.get("acme/skills/one").installation_status == InstallationStatus.INSTALLED
        assert any(event["operation"].startswith("installation") for event in registry.events())
    finally:
        registry.close()


def test_gzip_export_roundtrip_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "upstream"
    write_skill(source, "one/SKILL.md",
                skill_text("one", "A skill used to test gzip roundtrips.", license="MIT"))
    registry = new_registry(tmp_path)
    try:
        SkillSyncEngine(registry).ingest_local(source, repository="acme/skills", license="MIT")
        first = tmp_path / "a.jsonl.gz"
        second = tmp_path / "b.jsonl.gz"
        assert registry.export_jsonl(first) == 1
        assert registry.export_jsonl(second) == 1
        assert first.read_bytes() == second.read_bytes()

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other = new_registry(other_dir)
        try:
            counts = other.import_jsonl(first)
            assert counts["inserted"] == 1
            assert other.get("acme/skills/one").instructions == ""
        finally:
            other.close()
    finally:
        registry.close()
