---
name: spec-timeline
description: Define and maintain hard timeline anchors under spec/timeline/ (what happens when, causal order, deadlines, irreversible state transitions). Use to prevent time/knowledge continuity errors in outline/chapters.
---

# spec-timeline

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- You need hard time anchors / deadlines / ordering constraints that must not drift.
- Multi-POV or long arcs risk time/knowledge contradictions.
- The outline depends on “when” something happens, not just “what”.

## Quick start

1) Read existing `spec/timeline/` entries and summarize confirmed anchor points and non-negotiable order.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/timeline-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **hard**: order constraints, deadlines, and irreversible state changes.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/timeline/` is the **continuity backbone** for time: it prevents “time drift” (events moving around per convenience) and “knowledge drift” (people knowing things too early/late).

It exists to:
- keep causality believable (A happens before B; B requires A)
- enforce deadlines and pressure clocks
- make state transitions consistent (injuries, access, ownership, relationships)

## Module contract (Owns / Requires / Provides)

**Owns**
- Hard time anchors, ordering constraints, deadlines/clocks, cooldowns/travel/communication constraints when they are story-critical.
- “A before B” causality chains that must not drift.

**Does not own**
- Non-time state variables (injury/ownership/knowledge details) → `spec/continuity/`
- World baselines (distances, infrastructure) → `spec/world/`
- System mechanics (cooldown rules) → `spec/system/` (timeline can reference them for scheduling)
- Plot beat lists → outline/fine-outline

**Requires (upstream)**
- If travel/communication is important: `spec/world/` to ground durations and constraints.
- If powers/tech have cooldowns or timers: `spec/system/` to ground timing.

**Provides (downstream)**
- A single source of truth for “when” that outline/fine-outline/chapters must obey.
- Inputs for continuity tracking (knowledge timing) and regression checks.

## Definition of done (minimum viable)

At minimum, `spec/timeline/` should define:
- The timeline model used by the project (absolute dates vs relative markers)
- The key deadlines/clocks that create pressure (even if approximate)
- The non-negotiable ordering constraints for major reveals/irreversible events

## What belongs here (and what doesn’t)

Belongs in `spec/timeline/`:
- anchor events (absolute date/time or relative markers) that should not drift
- non-negotiable order constraints and dependency notes
- deadlines, clocks, cooldowns, travel/communication constraints (when they matter)
- irreversible state transitions (a treaty signed, a death confirmed, a system exposed, access revoked)

Does **not** belong in `spec/timeline/`:
- world baseline facts → `spec/world/`
- system mechanics rules → `spec/system/`
- detailed chapter beat lists → outline/fine-outline

## Outputs

- Spec entry files under `spec/timeline/` (one timeline object per file: an anchor event, a clock, a dependency chain), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/timeline-entry.md` as the default structure.

## How to write timeline entries

- Prefer simple, checkable statements: “Event A happens before Event B; B cannot occur unless A has occurred.”
- Separate “hard anchors” from “flexible sequencing”; only hard anchors belong in `spec/`.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a time constraint (deadline, travel time, irreversible order, knowledge sequence), add an anchor `@spec:<id>` pointing back to the relevant timeline entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Timeline Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Can you detect “time drift” from these entries alone?
- Are deadlines and irreversible transitions explicit enough to create pressure?
- Did you accidentally write a chapter plan instead of stable anchors?
