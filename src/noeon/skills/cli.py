from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .learning import MissionEvidence
from .model import SecurityDecision, SkillSource
from .runtime import build_universe, plan_mission, summarize_registry
from .security import scan_skill
from .sources import GitHubClient, read_sources, write_lock
from .sync import SkillSyncEngine


def _universe(args: argparse.Namespace):
    return build_universe(registry_path=args.registry, workspace=args.workspace,
                          skills_root=args.skills_root)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", default=".noeon/skills.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--skills-root", default=".noeon/skills")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noeon-skills", description="Noeon skill universe CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="discover and import skills from catalogued sources")
    _add_common(sync)
    sync.add_argument("--sources", default="catalog/sources.toml")
    sync.add_argument("--cache", default=".noeon/cache")
    sync.add_argument("--lock", default="catalog/sources.lock.json")
    sync.add_argument("--export", default="catalog/registry.jsonl.gz")
    sync.add_argument("--only", nargs="*")
    sync.add_argument("--limit", type=int)
    sync.add_argument("--workers", type=int, default=16)
    sync.add_argument("--no-lock", action="store_true")
    sync.add_argument("--no-export", action="store_true")
    sync.add_argument("--with-instructions", action="store_true")

    local = sub.add_parser("import-local", help="import a local directory of SKILL.md files")
    _add_common(local)
    local.add_argument("directory")
    local.add_argument("--repository", required=True)
    local.add_argument("--license", default="unknown")

    load = sub.add_parser("load", help="import a registry.jsonl(.gz) index without network")
    _add_common(load)
    load.add_argument("path", nargs="?", default="catalog/registry.jsonl.gz")

    search = sub.add_parser("search")
    _add_common(search)
    search.add_argument("query")
    search.add_argument("--role")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--category", action="append")
    search.add_argument("--min-quality", type=int, default=0)

    show = sub.add_parser("show")
    _add_common(show)
    show.add_argument("skill_id")

    stats = sub.add_parser("stats")
    _add_common(stats)

    install = sub.add_parser("install")
    _add_common(install)
    install.add_argument("skill_id")
    install.add_argument("--cache", default=".noeon/cache")
    install.add_argument("--force", action="store_true")

    uninstall = sub.add_parser("uninstall")
    _add_common(uninstall)
    uninstall.add_argument("skill_id")
    uninstall.add_argument("--cache", default=".noeon/cache")

    verify = sub.add_parser("verify")
    _add_common(verify)
    verify.add_argument("skill_id")
    verify.add_argument("--cache", default=".noeon/cache")

    assign = sub.add_parser("assign")
    _add_common(assign)
    assign.add_argument("role")
    assign.add_argument("goal")
    assign.add_argument("--budget", type=int, default=3000)

    plan = sub.add_parser("plan")
    _add_common(plan)
    plan.add_argument("goal")
    plan.add_argument("--role", action="append")
    plan.add_argument("--budget", type=int, default=3000)
    plan.add_argument("--output")

    scan = sub.add_parser("scan")
    _add_common(scan)
    scan.add_argument("skill_id")

    tools = sub.add_parser("tools")
    _add_common(tools)

    mcp = sub.add_parser("mcp")
    _add_common(mcp)
    mcp.add_argument("--config")

    learn = sub.add_parser("learn", help="draft a skill from mission evidence (JSON file)")
    _add_common(learn)
    learn.add_argument("evidence")

    approve = sub.add_parser("approve")
    _add_common(approve)
    approve.add_argument("skill_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    universe = _universe(args)
    try:
        return _dispatch(args, universe)
    finally:
        universe.close()


def _dispatch(args: argparse.Namespace, universe) -> int:
    if args.command == "sync":
        sources = [SkillSource.model_validate(item) for item in read_sources(args.sources)]
        engine = SkillSyncEngine(universe.registry, client=GitHubClient(cache_dir=args.cache),
                                 cache_dir=args.cache, max_workers=args.workers)
        reports = engine.sync(sources, only=args.only, limit_per_source=args.limit)
        payload = [report.model_dump(mode="json") for report in reports]
        if not args.no_export:
            universe.registry.export_jsonl(
                args.export, include_instructions=args.with_instructions
            )
        if not args.no_lock:
            write_lock(args.lock, payload,
                       export=None if args.no_export else args.export)
        _print({"sources": payload, "stats": summarize_registry(universe.registry)})
        return 0 if all(not report.errors for report in reports) else 1

    if args.command == "import-local":
        engine = SkillSyncEngine(universe.registry, client=GitHubClient())
        report = engine.ingest_local(args.directory, repository=args.repository,
                                     license=args.license)
        _print(report.model_dump(mode="json"))
        return 0

    if args.command == "load":
        count = universe.registry.import_jsonl(args.path)
        _print({"imported": count, "stats": summarize_registry(universe.registry)})
        return 0

    if args.command == "search":
        matches = universe.discovery.discover(
            args.query, role=args.role, limit=args.limit,
            categories=args.category, min_quality=args.min_quality,
        )
        _print({"semantic_available": universe.discovery.semantic_available,
                "results": [match.explain() for match in matches]})
        return 0

    if args.command == "show":
        record = universe.registry.get(args.skill_id)
        if record is None:
            _print({"error": f"unknown skill: {args.skill_id}"})
            return 1
        _print(record.model_dump(mode="json"))
        return 0

    if args.command == "stats":
        _print(summarize_registry(universe.registry))
        return 0

    if args.command == "install":
        engine = SkillSyncEngine(universe.registry, client=GitHubClient(cache_dir=args.cache),
                                 cache_dir=args.cache)
        result = engine.install(args.skill_id, force=args.force)
        _print({"skill_id": result.skill_id, "installed": result.installed,
                "reason": result.reason, "files": result.files})
        return 0 if result.installed else 1

    if args.command == "uninstall":
        engine = SkillSyncEngine(universe.registry, client=GitHubClient(cache_dir=args.cache),
                                 cache_dir=args.cache)
        _print({"uninstalled": engine.uninstall(args.skill_id)})
        return 0

    if args.command == "verify":
        engine = SkillSyncEngine(universe.registry, client=GitHubClient(cache_dir=args.cache),
                                 cache_dir=args.cache)
        verified = engine.verify(args.skill_id)
        _print({"skill_id": args.skill_id, "verified": verified})
        return 0 if verified else 1

    if args.command == "assign":
        assignment = universe.agents.assign(args.role, args.goal, budget_tokens=args.budget)
        _print(assignment.explain())
        return 0

    if args.command == "plan":
        plan = plan_mission(universe, args.goal, roles=args.role,
                            budget_tokens_per_role=args.budget)
        payload = plan.explain()
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _print(payload)
        return 0

    if args.command == "scan":
        record = universe.registry.get(args.skill_id)
        if record is None:
            _print({"error": f"unknown skill: {args.skill_id}"})
            return 1
        report = scan_skill(record.instructions)
        _print({"skill_id": args.skill_id, "decision": report.decision.value,
                "risk_score": report.risk_score,
                "findings": [finding.model_dump(mode="json") for finding in report.findings]})
        return 0 if report.decision != SecurityDecision.BLOCK else 2

    if args.command == "tools":
        _print({name: status.__dict__ for name, status in universe.tools.status().items()})
        return 0

    if args.command == "mcp":
        if args.config:
            universe.mcp = type(universe.mcp)(args.config)
        _print({"servers": [status.__dict__ for status in universe.mcp.status()],
                "issues": universe.mcp.validate()})
        return 0

    if args.command == "learn":
        evidence = MissionEvidence(**json.loads(Path(args.evidence).read_text(encoding="utf-8")))
        draft = universe.learning.draft(evidence)
        _print({"skill_id": draft.skill_id, "accepted": draft.accepted,
                "reason": draft.reason, "validation": draft.record.validation_status.value,
                "security": draft.record.security_status.value,
                "quality": draft.record.quality_score})
        return 0 if draft.accepted else 1

    if args.command == "approve":
        result = universe.learning.approve(args.skill_id)
        _print({"skill_id": result.skill_id, "approved": result.accepted,
                "reason": result.reason})
        return 0 if result.accepted else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
