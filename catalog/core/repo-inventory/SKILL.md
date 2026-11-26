---
name: repo-inventory
description: Produce a factual inventory of a repository before changing it. Use when starting work in an unfamiliar codebase or when a mission needs a baseline of files, languages and large assets.
license: proprietary
allowed-tools: [Read, Bash]
permissions: [read, execute]
version: 1.0.0
tags: [repository, inventory, discovery, engineering]
---

# Repository inventory

## When to use

Use this skill before planning changes in an unfamiliar repository, or when a
mission needs to confirm what exists instead of guessing.

## Workflow

1. Run `scripts/inventory.py --path .` from the repository root.
2. Read the JSON report: file count, extension histogram, largest files,
   detected languages and top-level directories.
3. Use the report to choose what to read next. Do not infer a stack from a single
   file when the histogram contradicts it.

## Output

A single JSON object with `root`, `file_count`, `by_extension`, `by_directory`,
`largest` and `languages`.

## Verification

Run `python3 scripts/inventory.py --path . --limit 5` and confirm `file_count` is
greater than zero and `by_extension` is not empty.
