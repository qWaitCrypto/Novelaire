---
name: spec-objects
description: Define and maintain key objects/resources canon under spec/objects/ (what it is, how it works, limits, ownership/flow, failure, interfaces with system/plot). Use to prevent “magic props” and continuity drift.
---

# spec-objects

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- A key object/resource/tool is driving scenes or solving problems.
- Props are starting to feel like “magic items” with shifting abilities.
- Ownership/transfer/scarcity needs to be constrained to keep causality believable.

## Quick start

1) Read existing `spec/objects/` entries and summarize confirmed object definitions + constraints.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/object-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **constraint-oriented**: usage rules, limits, ownership/flow, failure modes.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/objects/` is the **prop consistency layer**: it prevents key items/resources from becoming scene-convenience tools.

It exists to:
- keep object properties stable across chapters
- prevent “suddenly it can do X” drift
- make scarcity and ownership meaningful (who has what, and what that implies)

## Module contract (Owns / Requires / Provides)

**Owns**
- Key objects/resources that recur and affect causality: what it is, what it does, limits, failure, ownership/flow.

**Does not own**
- Mechanism rules → `spec/system/` (objects may invoke system rules; don’t redefine them here)
- Broad scarcity/economy baselines → `spec/world/`
- Character motives/arc → `spec/characters/` (objects can be owned by characters)

**Requires (upstream)**
- Often `spec/system/` for interface boundaries (what the object can/cannot do via the system).
- Often `spec/world/` for scarcity and enforcement consequences.

**Provides (downstream)**
- Stable constraints so scenes cannot “invent” new prop abilities or ignore ownership.

## Definition of done (minimum viable)

For each key object/resource, the entry should state:
- What it is (definition/scope) and what it is not
- What it can do and what it cannot do (anti-loophole)
- Limits, durability/failure modes, and typical misuse
- Ownership/transfer rules when they matter to consequences

## What belongs here (and what doesn’t)

Belongs in `spec/objects/`:
- key objects/resources that recur or have plot/system implications
- usage rules, limits, durability/failure conditions
- ownership/transfer rules; economic or institutional constraints if relevant
- interfaces with systems (what triggers what; what cannot be bypassed)

Does **not** belong in `spec/objects/`:
- broad world economics/history baselines → `spec/world/`
- system mechanics rules → `spec/system/`
- one-off scene details that won’t recur → drafts/outline

## Outputs

- Spec entry files under `spec/objects/` (one object per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/object-entry.md` as the default structure.

## How to write object entries

- Make “what it cannot do” explicit (anti-loophole).
- Track ownership and flow when it matters to consequences.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on an object constraint (availability, limits, failure, ownership), add an anchor `@spec:<id>` pointing back to the relevant object entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Objects Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Are properties/limits stable enough to prevent “magic prop” behavior?
- Are ownership and scarcity explicit when they should drive consequences?
- Did you accidentally define system mechanics here instead of in `spec/system/`?
