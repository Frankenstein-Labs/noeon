from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from noeon.execution import BoundedExecutor

from .manifest import build_record
from .model import InstallationStatus, Origin, SecurityDecision, SkillRecord, ValidationStatus, slugify
from .registry import SkillRegistry


@dataclass
class MissionEvidence:
    goal: str
    role: str = "architect"
    commands: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    test_command: str = ""
    test_output: str = ""
    notes: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return bool(self.goal.strip() and (self.commands or self.changed_files) and self.test_command)


@dataclass
class DraftResult:
    skill_id: str
    record: SkillRecord
    text: str
    accepted: bool
    reason: str = ""


class SkillLearningEngine:
    """Turns a completed mission into a candidate skill, quarantined until verified."""

    def __init__(self, registry: SkillRegistry, workspace: str | Path = ".") -> None:
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()

    def draft(self, evidence: MissionEvidence) -> DraftResult:
        if not evidence.sufficient:
            raise ValueError(
                "insufficient evidence: a draft needs a goal, commands or changed files, and a test command"
            )
        slug = slugify(evidence.goal)[:48]
        digest = hashlib.sha256(evidence.goal.encode()).hexdigest()[:8]
        skill_id = f"noeon/generated/{slug}-{digest}"
        text = self._render(evidence)
        built = build_record(
            repository="noeon/generated",
            commit="generated",
            path=f"{slug}/SKILL.md",
            text=text,
            declared_license="proprietary",
            allowlisted=True,
            installation=InstallationStatus.IMPORTED,
            origin=Origin.GENERATED,
        )
        record = built.record
        record.skill_id = skill_id
        record.source_url = ""
        record.metadata["approval"] = "pending"
        record.metadata["evidence"] = {
            "role": evidence.role,
            "commands": evidence.commands[:20],
            "changed_files": evidence.changed_files[:50],
            "test_command": evidence.test_command,
            "skills_used": evidence.skills_used[:20],
        }
        self.registry.upsert(record)
        self.registry.record_event(skill_id, "draft", "generated from mission evidence")
        accepted = (
            record.validation_status == ValidationStatus.VALID
            and record.security_status != SecurityDecision.BLOCK
            and bool(evidence.test_command)
        )
        return DraftResult(skill_id, record, text, accepted,
                           "ready for verification" if accepted else "failed validation or security gate")

    def approve(self, skill_id: str, *, timeout_seconds: int = 120) -> DraftResult:
        record = self.registry.get(skill_id)
        if record is None:
            raise KeyError(skill_id)
        if record.origin != Origin.GENERATED:
            raise ValueError("only generated skills can be approved through this path")
        evidence = record.metadata.get("evidence") or {}
        test_command = str(evidence.get("test_command", "")).strip()
        if not test_command:
            raise ValueError("generated skill has no verification command")
        argv = test_command.split()
        result = BoundedExecutor(self.workspace, timeout_seconds).run(argv, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            record.metadata["approval"] = "rejected"
            record.metadata["verification"] = {
                "command": test_command, "returncode": result.returncode,
                "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:],
            }
            record.installation_status = InstallationStatus.UNINSTALLED
            self.registry.upsert(record)
            self.registry.record_event(skill_id, "approve:rejected", f"rc={result.returncode}")
            return DraftResult(skill_id, record, record.instructions, False, "verification failed")
        record.metadata["approval"] = "approved"
        record.metadata["approved_at"] = datetime.now(UTC).isoformat()
        record.metadata["verification"] = {
            "command": test_command, "returncode": 0,
            "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:],
        }
        record.installation_status = InstallationStatus.INSTALLED
        record.last_verified = datetime.now(UTC)
        self.registry.upsert(record)
        self.registry.record_event(skill_id, "approve", "verification passed")
        return DraftResult(skill_id, record, record.instructions, True, "approved")

    def export(self, skill_id: str, directory: str | Path) -> Path:
        record = self.registry.get(skill_id)
        if record is None:
            raise KeyError(skill_id)
        target = Path(directory).expanduser() / slugify(record.name) / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(record.instructions if record.instructions else "", encoding="utf-8")
        return target

    def _render(self, evidence: MissionEvidence) -> str:
        steps = "\n".join(f"{index}. `{command}`" for index, command in enumerate(evidence.commands, 1))
        changed = "\n".join(f"- `{path}`" for path in evidence.changed_files) or "- none recorded"
        notes = "\n".join(f"- {note}" for note in evidence.notes) or "- none"
        used = "\n".join(f"- {skill}" for skill in evidence.skills_used) or "- none"
        return f"""---
name: {slugify(evidence.goal)[:48]}
description: >
  Procedure extracted from a verified Noeon mission: {evidence.goal.strip()[:300]}
  Use when a similar task recurs in the same repository or stack. Includes the
  commands that worked and the verification command that passed.
metadata:
  author: noeon
  version: "0.1.0"
  origin: generated
license: proprietary
allowed-tools: Bash, Read, Write
---

# {evidence.goal.strip()[:120]}

## When to use

Use this procedure when the mission goal matches the one recorded below and the
repository exposes the same tooling. Re-check the preconditions before running it.

## Mission goal

{evidence.goal.strip()}

## Workflow

{steps or "1. No command recorded"}

## Changed files

{changed}

## Verification

Command that passed during approval:

```bash
{evidence.test_command}
```

Recorded output:

```text
{evidence.test_output.strip()[:1500] or "(empty)"}
```

## Notes

{notes}

## Skills used

{used}
"""
