---
name: gate-spec
description: Run the Spec Gate (PASS/WARN/FAIL) before moving from spec to outline. Use to verify premise/system/characters/timeline readiness and detect spec-level contradictions.
---

# gate-spec

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user wants to start outlining (or you are about to run `workflow-outline`).
- The user wants to start writing chapters but spec readiness is unclear.
- Spec has been edited/backfilled and you need to re-check readiness.

## What this gate protects

This gate prevents downstream drift by ensuring `spec/` is:
- **usable** (premise + constraints exist, not just nouns)
- **internally consistent** (no conflicting facts/rules)
- **actionable** (enough anchors to constrain outline decisions)

## Inputs (what to read)

- `spec/premise/*` (must exist and be usable)
- `spec/system/*` (only the mechanisms that will be used by the story)
- `spec/characters/*` (at least protagonist + core opposition)
- One of:
  - `spec/timeline/*` (hard time anchors), or
  - `spec/continuity/*` (state anchors), or
  - both (best)
- Optional (as used): `spec/world/*`, `spec/factions/*`, `spec/locations/*`, `spec/objects/*`, `spec/glossary/*`

## Quick start

1) Inspect `spec/` coverage:
   - use `project__glob` to see which spec subfolders contain entries
   - optionally use `spec__query` to surface spec parsing warnings
2) Read the minimum set of key entries (premise/system/characters/timeline).
3) Output a Gate Report (format below).

## Evidence tooling (how to stay concrete)

- Use `project__glob(patterns=[...])` to inventory spec files and detect empty domains.
- Use `spec__query(query=...)` to refresh the spec index and surface parsing warnings.
- Use `spec__get(id=...)` to read specific entries by id when the outline references `@spec:<id>`.
- Use `project__read_text` / `project__read_text_many` to quote exact passages that justify a finding.

## Gate Report format

- **Target**: Spec
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / backfill / revise upstream / rollback

Severity meanings:
- **FAIL**: blocks downstream work
- **WARN**: can proceed, but must be tracked and re-checked
- **NOTE**: optimization suggestion

## Minimum checks (v1)

PASS requires at least:
- Premise is usable (core conflict + reader promise exists).
- Key system/mechanism constraints are usable (boundaries/costs; no pure-noun “magic”).
- Key characters are usable (motives/goals support the core conflict).
- At least one hard anchor exists (timeline/state anchor that must not drift).

FAIL if any:
- Premise conflict/promise missing → can’t detect drift.
- Key rules are only nouns (no boundaries/costs) → solutions can’t be constrained.
- Major contradictions inside spec (duplicate ids, conflicting rules/facts).

WARN if:
- A clear “undecided list” exists, but does not block current work.

## Suggestions (typical fixes)

- Missing premise → use `spec-premise` to create `premise/core`.
- Missing system constraints → use `spec-system` for the mechanisms actually used.
- Missing key characters → use `spec-characters` for protagonist/core opposition.
- Missing anchors → use `spec-timeline` (or `spec-continuity`) to add non-negotiable anchors.

## Fix routing (where to repair)

- Missing/weak premise → `spec-premise` (do not “fix it in outline”).
- System rules are nouns only → `spec-system` (add boundaries/costs/failure/counters).
- Character motivations unclear → `spec-characters` (add goals/boundaries/state variables).
- No anchors → `spec-timeline` / `spec-continuity`.
- Contradictions inside spec → resolve in spec first (and re-run this gate).

## Constraints

- Do not modify `spec/` while running this gate; only report findings.
- Findings MUST be anchored to concrete text (file + line/quote).

## Self-check

- Did you keep the report concrete (file/id + actionable fix)?
- Did you block progress on FAIL?
