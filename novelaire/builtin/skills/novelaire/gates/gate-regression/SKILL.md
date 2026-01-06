---
name: gate-regression
description: Run the Regression Gate at milestones. Use to scan written chapters for consistency (timeline, knowledge, character state, system boundaries) and produce a prioritized fix list.
---

# gate-regression

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The project reached a milestone (e.g., every 5–10 chapters, end of an arc/volume).
- The user wants to “回测/回归/检查有没有穿帮/检查逻辑一致性”.
- You are about to make a large upstream change and want to measure blast radius first.

## What this gate protects

This gate is a milestone “safety scan” to catch slow drift that accumulates over many chapters:
- continuity state resets (injuries/debts/permissions/possessions)
- knowledge boundary leaks (who knows what when)
- timeline contradictions and missing time passage
- system boundary erosion (costs/limits/failure ignored)
- dropped obligations (foreshadowing promises, faction reactions)

## Quick start

1) Identify the scope (which chapters/arc/milestone).
2) Scan for consistency:
   - timeline order and anchors
   - who-knows-what boundaries
   - character state variables (injury, debt, access, possessions)
   - system rule execution (costs/limits/failure)
3) If `spec/modules/*` are enabled, include module-specific checks.
4) Output a Gate Report (no need to write it to disk unless requested).

## Inputs (what to read)

- Chapter range under project `chapters/`.
- Relevant canon sources:
  - `spec/continuity/*`, `spec/timeline/*`, `spec/system/*`
  - optionally `outline/outline.md` and `outline/fine-outline.md` for intended state transitions

## Evidence tooling (how to stay concrete)

- Use `project__glob` to list chapter files in scope.
- Use `project__read_text_many` to load the scoped chapters (bounded) for inspection.
- Use `project__search_text` to locate recurring entities/terms and anchor findings to line numbers.
- Use `spec__query` / `spec__get` to load the relevant canon constraints.

## Fix routing (where to repair)

- Contradiction with canon → decide whether canon is wrong (rare) or prose drifted (common); fix upstream first when the issue is structural.
- Repeated drift pattern (e.g., system cheating) → tighten spec/system rules and add anchors to outline/fine-outline.
- Single-chapter slip → revise chapter text, and add a continuity note if needed to prevent recurrence.

## Gate Report format

- **Target**: Regression
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / revise upstream / prioritize fixes

## Minimum checks (v1)

PASS/WARN/FAIL is based on severity of findings:
- **FAIL**: contradictions or drift that break core logic/rules/promise.
- **WARN**: issues that can be deferred but must be tracked.
- **NOTE**: optimizations.

## Constraints

- Do not modify story files while running this gate; only report findings.
- Findings MUST be anchored to concrete text (file + line or quote).

## Self-check

- Is the fix order “blockers first, optimizations later”?
- Did you check continuity variables and knowledge boundaries, not only plot beats?
