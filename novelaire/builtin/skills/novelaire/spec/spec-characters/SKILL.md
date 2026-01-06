---
name: spec-characters
description: Define and maintain character canon under spec/characters/ (identity, motive, resources, behavioral boundaries, relationships, state variables). Use when designing main cast, or when outline/chapters show OOC risk.
---

# spec-characters

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- You are designing the main cast (protagonist, core opposition, key allies).
- Dialogue/actions risk OOC, or motivations feel convenient.
- You need stable state variables to prevent “reset” across chapters.

## Quick start

1) Read existing `spec/characters/` entries and summarize confirmed character invariants.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/character-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **stable** and **action-constraining** (so you can judge “would they do this?”).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/characters/` is the **OOC prevention layer**: it locks down what a character wants, what they can do, what they won’t do, and what relationships/constraints shape their choices.

It exists to:
- keep behavior consistent across chapters, even as situations change
- make conflict credible (motives + constraints create predictable friction)
- reduce “personality drift” and “scene convenience”

## Module contract (Owns / Requires / Provides)

**Owns**
- Canon character constraints: motives/goals, behavioral boundaries, resources/capability ceilings, relationship constraints, state variables that must persist.
- “Would they do this?” decision logic: what they refuse, what they must protect, what it costs them to bend.

**Does not own**
- World baselines and institutions → `spec/world/`
- System mechanics rules → `spec/system/` (characters reference them; do not redefine)
- Timeline anchors and ordering → `spec/timeline/`
- Plot beats → outline/fine-outline

**Requires (upstream)**
- Preferably `spec/premise/` so character roles/arc pressure match the reader promise.
- If the story has strong mechanisms: `spec/system/` for ability boundaries.
- If organizations matter: `spec/factions/` for affiliation constraints.

**Provides (downstream)**
- Stable constraints for outline/fine-outline/chapter writing: consistent action, dialogue pressure, believable escalation.
- Inputs for continuity tracking (state variables) and regression checks (OOC risk).

**Routing rule**
- If a chapter introduces a new stable character constraint (new boundary, new resource, new secret revealed), update the character entry (or explicitly decide it’s not canon yet).

## Definition of done (minimum viable)

At minimum, for each **main** character, the entry should make these answerable without guessing:
- What they want (long-term + current objective) and what they fear losing
- What they will not do / cannot do / would only do under specific conditions
- What resources/capabilities the story can rely on (and their ceilings)
- Who/what constrains them (key relationships, obligations, affiliations)
- What must persist across chapters (state variables: injury/debt/knowledge/permissions/possessions)

## What belongs here (and what doesn’t)

Belongs in `spec/characters/`:
- stable truths: identity, status/position, long-term goals, fears/taboos
- resources/capabilities the story can rely on (and their boundaries)
- behavioral constraints (“will not”, “cannot”, “would only if…”)
- key relationships and how they constrain choices
- state variables that must be tracked across chapters (injury, debts, secrets known, permissions, possessions)

Does **not** belong in `spec/characters/`:
- world baseline facts/institutions → `spec/world/`
- system mechanics (magic/tech rules) → `spec/system/`
- plot beats / scene plans → outline/fine-outline

## Outputs

- Spec entry files under `spec/characters/` (one character per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/character-entry.md` as the default structure.

## How to write character entries

- Prioritize **decision constraints** over personality adjectives.
- Make boundaries explicit: “will not”, “cannot”, “would rather”, “must”.
- Track what changes slowly (values, core wounds, long goals) vs what changes quickly (current mission, injuries).
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline relies on a character constraint (motivation, boundary, relationship, knowledge state), add an anchor `@spec:<id>` pointing back to the relevant character entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Characters Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Can you predict what the character will do under pressure from this entry alone?
- Are boundaries strong enough to prevent “whatever the scene needs” behavior?
- Did you accidentally encode plot beats instead of stable canon?
