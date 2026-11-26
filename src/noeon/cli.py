from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import Mission
from .orchestrator import NoeonOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(prog="noeon", description="Noeon autonomous engineering engine")
    parser.add_argument("goal")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--model")
    parser.add_argument("--role")
    parser.add_argument("--registry", default=".noeon/skills.sqlite3")
    parser.add_argument("--skills", action="store_true", help="load the local skill catalog")
    parser.add_argument("--skill-budget", type=int, default=6000)
    args = parser.parse_args()

    universe = None
    if args.skills:
        from .skills.runtime import build_universe

        universe = build_universe(registry_path=args.registry, workspace=args.workspace)
    try:
        mission = Mission(goal=args.goal, workspace=args.workspace, model=args.model,
                          agent_role=args.role, skill_budget_tokens=args.skill_budget)
        result = NoeonOrchestrator(skills=universe).run(mission)
    finally:
        if universe is not None:
            universe.close()
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.status.value == "succeeded" else 1
