from __future__ import annotations

from pathlib import Path

from skill_helpers import make_universe, skill_text

from noeon.agents import default_registry as default_agents
from noeon.skills import InstallationStatus, build_record


def _add(registry, name: str, description: str, *, install: bool = True):
    record = build_record(
        repository="acme/skills", commit="abc", path=f"{name}/SKILL.md",
        text=skill_text(name, description, license="MIT"),
    ).record
    if install:
        record.installation_status = InstallationStatus.INSTALLED
    registry.upsert(record)
    return record


def test_assign_respects_role_limit_and_persists(tmp_path: Path) -> None:
    universe = make_universe(tmp_path)
    try:
        for index in range(20):
            _add(universe.registry, f"react-skill-{index}",
                 f"React component engineering skill {index}. Use when building React interfaces.")
        assignment = universe.agents.assign("frontend", "build a react interface", budget_tokens=8000)
        assert 0 < len(assignment.matches) <= universe.agents.profile("frontend").max_skills
        stored = universe.registry.by_agent("frontend")
        assert {record.skill_id for record, _ in stored} == set(assignment.skill_ids)
        assert assignment.context.skill_ids
    finally:
        universe.close()


def test_borrow_requires_compatibility_and_assignment(tmp_path: Path) -> None:
    universe = make_universe(tmp_path)
    try:
        record = _add(universe.registry, "react-forms",
                      "Build accessible React forms. Use when interface forms need validation.")
        universe.registry.assign("frontend", [record.skill_id], reason="owner")

        allowed, reason = universe.agents.borrow("designer", "frontend", record.skill_id)
        assert allowed, reason
        assert record.skill_id in {item.skill_id for item, _ in universe.registry.by_agent("designer")}

        denied, reason = universe.agents.borrow("database", "frontend", record.skill_id)
        assert not denied
        assert "permitted" in reason

        missing, reason = universe.agents.borrow("designer", "research", record.skill_id)
        assert not missing
        assert "not assigned" in reason
    finally:
        universe.close()


def test_request_finds_skills_for_requester(tmp_path: Path) -> None:
    universe = make_universe(tmp_path)
    try:
        _add(universe.registry, "sqlite-migrations",
             "Plan SQLite schema migrations. Use when changing database schemas.")
        matches = universe.agents.request("database", "sqlite schema migration", limit=3)
        assert matches
        assert matches[0].record.category in {"data", "backend"}
    finally:
        universe.close()


def test_sync_agent_registry_populates_specs(tmp_path: Path) -> None:
    universe = make_universe(tmp_path)
    try:
        _add(universe.registry, "react-forms",
             "Build accessible React forms. Use when interface forms need validation.")
        _add(universe.registry, "fastapi-endpoints",
             "Design FastAPI backend endpoints. Use when building a REST API server.")
        agents = default_agents(max_agents=20)
        assignments = universe.agents.sync_agent_registry(agents, "build a web app", roles=["frontend", "backend"])
        assert set(assignments) == {"frontend", "backend"}
        frontend = agents.get("frontend")
        assert frontend.skills
        assert all(skill.tool_permissions is not None for skill in frontend.skills)
    finally:
        universe.close()


def test_assign_deduplicates_same_name_and_content(tmp_path: Path) -> None:
    from noeon.skills import build_record

    universe = make_universe(tmp_path)
    try:
        text = skill_text("senior-backend",
                          "Build FastAPI backend APIs with authentication. Use when writing API servers.")
        for repo in ("acme/one", "acme/two"):
            record = build_record(repository=repo, commit="abc", path="senior-backend/SKILL.md",
                                  text=text, declared_license="MIT").record
            record.installation_status = InstallationStatus.INSTALLED
            universe.registry.upsert(record)
        assignment = universe.agents.assign("backend", "build a fastapi backend api", budget_tokens=2000)
        names = [match.record.name for match in assignment.matches]
        assert names.count("senior-backend") == 1
    finally:
        universe.close()
