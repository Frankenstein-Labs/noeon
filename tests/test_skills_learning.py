from __future__ import annotations

from pathlib import Path

import pytest
from skill_helpers import new_registry

from noeon.skills import InstallationStatus, MissionEvidence, SkillLearningEngine


def _engine(tmp_path: Path) -> SkillLearningEngine:
    registry = new_registry(tmp_path)
    return SkillLearningEngine(registry, tmp_path)


def test_draft_requires_evidence(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(ValueError):
        engine.draft(MissionEvidence(goal="do something", test_command="python3 --version"))


def test_draft_is_quarantined_until_approved(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    evidence = MissionEvidence(
        goal="Add a health endpoint to the backend API and verify it",
        role="backend",
        commands=["python3 -m pytest -q"],
        changed_files=["app.py"],
        test_command="python3 --version",
        test_output="Python 3.13.0",
        skills_used=["acme/skills/fastapi-endpoints"],
    )
    draft = engine.draft(evidence)
    assert draft.accepted
    assert draft.record.origin.value == "generated"
    assert draft.record.metadata["approval"] == "pending"
    assert draft.record.installation_status == InstallationStatus.IMPORTED

    approved = engine.approve(draft.skill_id)
    assert approved.accepted
    assert approved.record.metadata["approval"] == "approved"
    assert approved.record.installation_status == InstallationStatus.INSTALLED
    assert approved.record.metadata["verification"]["returncode"] == 0


def test_failed_verification_rejects_draft(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    draft = engine.draft(MissionEvidence(
        goal="Run a failing verification",
        commands=["python3 --version"],
        test_command="python3 -m module_that_does_not_exist_xyz",
    ))
    result = engine.approve(draft.skill_id)
    assert not result.accepted
    assert result.record.metadata["approval"] == "rejected"
    assert result.record.installation_status == InstallationStatus.UNINSTALLED


def test_export_writes_skill_file(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    draft = engine.draft(MissionEvidence(
        goal="Export a generated procedure",
        commands=["python3 --version"],
        test_command="python3 --version",
    ))
    target = engine.export(draft.skill_id, tmp_path / "export")
    assert target.name == "SKILL.md"
    assert "Export a generated procedure" in target.read_text(encoding="utf-8")
