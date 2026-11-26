---
name: web-app-blueprint
description: Turn a product request into an implementation blueprint for a web application. Use when a mission asks for a new web application, dashboard or API and needs design, frontend, backend and QA responsibilities made explicit before coding.
license: proprietary
allowed-tools: [Read, Write, Edit]
permissions: [read]
version: 1.0.0
tags: [architecture, frontend, backend, design, planning]
---

# Web application blueprint

## When to use

Use at the start of a request that creates or reshapes a web application. Skip it
for a one-line fix in an existing feature.

## Workflow

1. Restate the user-visible outcome in one sentence.
2. Inventory the current stack from real files. Do not assume a framework.
3. Define the smallest end-to-end slice: one route or screen, its data, its test.
4. Record decisions in four blocks:
   - Design: hierarchy, states (empty, loading, error), accessibility constraints.
   - Frontend: components, data fetching, validation, error surface.
   - Backend: endpoints, schemas, persistence, auth boundaries, failure modes.
   - QA: the exact command that proves the slice works.
5. Name the files to create or change. Keep the slice shippable without the rest.
6. Hand the slice to the implementer with the QA command, not with a vibe.

## Output

A short blueprint with the slice, file list, API contract, UI states and the
verification command. Each later decision must cite one of these blocks.

## Verification

The blueprint is complete only when the QA block contains a command that can run
in this repository, and the file list names real paths.
