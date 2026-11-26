"""Run pytest and print a JSON summary of the result."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def parse_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for line in output.splitlines():
        if " passed" not in line and " failed" not in line and " error" not in line:
            continue
        for value, label in SUMMARY.findall(line):
            key = "errors" if label.startswith("error") else label
            counts[key] = max(counts[key], int(value))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pytest and summarise the result")
    parser.add_argument("--path", default=".")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    path = Path(args.path).resolve()
    if not path.is_dir():
        print(json.dumps({"error": f"not a directory: {path}"}))
        return 2

    command = [sys.executable, "-m", "pytest", "-q"]
    try:
        completed = subprocess.run(
            command, cwd=path, capture_output=True, text=True, timeout=args.timeout,
            check=False,
        )
    except FileNotFoundError:
        print(json.dumps({"error": "pytest is not installed", "command": command}))
        return 2
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "pytest timed out", "timeout": args.timeout}))
        return 124

    output = (completed.stdout + completed.stderr).strip()
    counts = parse_counts(output)
    lines = output.splitlines()
    print(json.dumps({
        "command": command,
        "returncode": completed.returncode,
        **counts,
        "summary": next(
            (line for line in reversed(lines)
             if "passed" in line or "failed" in line or "no tests ran" in line),
            lines[-1] if lines else "",
        ),
        "tail": lines[-80:],
    }, indent=2))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
