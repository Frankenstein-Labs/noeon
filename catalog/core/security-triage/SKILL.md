---
name: security-triage
description: Triage a security finding before changing code. Use when a scanner, dependency audit or reviewer reports a vulnerability and the mission must decide between fixing, mitigating or accepting the risk.
license: proprietary
allowed-tools: [Read, Bash]
permissions: [read]
version: 1.0.0
tags: [security, triage, dependencies, review]
---

# Security triage

## When to use

Use for every finding that blocks a release, and for findings marked high or
critical by a scanner. Do not use it to justify ignoring a finding you did not
reproduce.

## Workflow

1. Reproduce or locate the finding in the real code path. Record the file, line
   and the input that reaches it.
2. Decide exploitability: is the path reachable from untrusted input, and what
   does the attacker gain?
3. Choose one action and record it:
   - Fix: change the code or pin a patched dependency.
   - Mitigate: constrain the input, the permission or the network path.
   - Accept: state the compensating control and the review date.
4. Add a regression test that fails before the fix and passes after it.
5. Report evidence, not adjectives.

## Output

A triage note with finding, reachability, decision, evidence command and the test
that locks the behaviour.

## Limits

Static scanners over-report. A scanner hit is a lead, not a verdict. This skill
never suppresses a critical finding without a named owner and a date.
