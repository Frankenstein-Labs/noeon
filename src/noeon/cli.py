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
    args = parser.parse_args()
    result = NoeonOrchestrator().run(Mission(goal=args.goal, workspace=args.workspace, model=args.model))
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.status.value == "succeeded" else 1
