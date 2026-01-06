---
name: gate-outline
description: Run the Outline Gate (PASS/WARN/FAIL) before moving from outline to fine-outline. Use to ensure outline obeys spec constraints and anchors key ambiguity points.
---

# gate-outline

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- An outline exists and you are about to start fine-outline (`workflow-fine-outline`).
- The user asks “能不能开始写细纲/写正文了？” and you need to verify the outline is safe.
- The outline was recently edited and needs a readiness re-check.

## Quick start

1) Read the outline artifact(s) under project `outline/` (usually `outline/outline.md`).
2) Spot-check conflicts against `spec/` (premise promise, system limits, world/faction constraints).
3) Check that key ambiguity points include `@spec:<id>` anchors.
4) If the outline contains “Undecided / Open Questions”, verify they are carried forward (and treated as blockers when needed).
5) Output a Gate Report.

## What this gate protects

This gate prevents you from writing fine-outline on top of an outline that is:
- off-premise (promise drift)
- “system-cheating” (solutions appear without bounded rules/costs)
- missing anchors at key ambiguity points (numbers, terms, rule boundaries, time anchors)
- silently carrying undecided assumptions (which later become contradictions)

## Inputs (what to read)

- Outline artifact(s) under project `outline/` (prefer `outline/outline.md`).
- Relevant spec domains:
  - always: `spec/premise/*`, `spec/system/*`
  - as needed: `spec/world/*`, `spec/factions/*`, `spec/timeline/*`, `spec/continuity/*`, `spec/glossary/*`

## Evidence tooling (how to stay concrete)

- Use `project__glob` to locate outline files.
- Use `project__read_text` / `project__read_text_many` to quote exact outline passages.
- Use `project__search_text(query=\"@spec:\", path=\"outline\")` to inventory anchors.
- Use `spec__query` / `spec__get` to locate and read the referenced constraints.

## Fix routing (where to repair)

- Missing core constraint → backfill spec first (`workflow-extract-backfill` + `spec-*`), then update outline.
- Missing anchor (spec exists) → add `@spec:<id>` at the ambiguity point in the outline.
- Outline contradicts spec → revise outline (preferred) or explicitly change spec (only with user approval), then re-run this gate.
- Motivation → action → consequence breaks → revise outline beats (do not defer to prose).

## Gate Report format

- **Target**: Outline
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / backfill spec / revise outline / rollback

## Minimum checks (v1)

PASS:
- Outline does not conflict with spec.
- If outline introduces a new *core* rule/setting, spec is backfilled first (or explicitly marked undecided).
- Key ambiguity points (rules/boundaries/costs/terms/numbers/time anchors) can point to spec anchors.
- Mainline causality supports the premise (how conflict escalates and resolves to satisfy the promise).

FAIL:
- Introduces a new core rule that affects mainline, but spec has no constraints and it’s not marked undecided.
- Motivation → action → consequence breaks so badly the logic can’t close.

WARN:
- Some anchors are missing but can be added without re-architecting the outline.
- “Undecided / Open Questions” exist but are clearly scoped and do not block current progress.

## Constraints

- Do not modify `spec/` or `outline/` while running this gate; only report findings.
- Findings MUST be anchored to concrete locations (file + heading, or file + line when available).

## Self-check

- Are FAIL reasons truly blocking downstream work?
- Are suggested fixes upstream-first (outline/spec), not “patch prose later”?
