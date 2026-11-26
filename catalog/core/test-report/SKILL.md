---
name: test-report
description: Run the project test suite and return a structured pass/fail report. Use when a mission needs objective evidence about tests before or after a change.
license: proprietary
allowed-tools: [Read, Bash]
permissions: [read, execute]
version: 1.0.0
tags: [testing, qa, evidence, engineering]
---

# Test report

## When to use

Use after any code change, and before claiming that a mission is verified. The
report is evidence, not a substitute for reading the failing test.

## Workflow

1. Run `scripts/test_report.py` from the repository root.
2. Read `returncode`, `passed`, `failed` and `summary`.
3. If `failed` is greater than zero, fix the smallest real cause and rerun.
4. Never report success when `returncode` is non-zero.

## Output

JSON with `command`, `returncode`, `passed`, `failed`, `skipped`, `summary` and
the last 80 lines of output.

## Verification

The script itself must exit 0 on a passing suite and non-zero on a failing one;
it returns the underlying pytest exit code.

## Limits

The script runs the suite in the current working directory with the sanitized
skill environment. It does not install dependencies.
