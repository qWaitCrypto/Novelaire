---
name: spec-continuity
description: Define and maintain continuity constraints under spec/continuity/ (tracked state variables, knowledge boundaries, invariants, continuity checklists). Use to prevent “state reset” and cross-chapter contradictions.
---

# spec-continuity

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The story has state that must persist across chapters (injuries, debt, permissions, possessions, secrets).
- You see “state reset” or inconsistent who-knows-what boundaries.
- You need explicit invariants and update rules to support regression checks.

## Quick start

1) Read existing `spec/continuity/` entries and summarize tracked variables and invariants.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/continuity-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **trackable**: state variables, who-knows-what, ownership, injuries, permissions.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/continuity/` is the **anti-reset layer**: it defines what must persist across chapters and what “cannot be forgotten”.

It exists to:
- prevent injuries/debts/knowledge from mysteriously disappearing
- enforce consistent information flow (“who knows what when”)
- provide a single place to run continuity regression checks

## Module contract (Owns / Requires / Provides)

**Owns**
- Tracked state variables that must persist (injury/debt/ownership/access/knowledge/relationship state).
- Invariants (“must not contradict”), and update rules (what changes which variable).
- A regression checklist for continuity-sensitive revisions.

**Does not own**
- Timeline anchors (“when”) → `spec/timeline/`
- Full character profiles → `spec/characters/` (continuity references character state variables)
- World baselines or system mechanics

**Requires (upstream)**
- Often depends on: `spec/characters/`, `spec/objects/`, `spec/factions/`, and `spec/narrative/` (for knowledge boundaries).
- If timing matters: `spec/timeline/` provides the anchor points that constrain updates.

**Provides (downstream)**
- A single source of truth for “what must still be true” at any point in the story.
- A stable checklist for regression reviews of chapters and arcs.

**Routing rule**
- If a chapter changes a tracked variable (injury worsens, access revoked, someone learns a secret), update the continuity tracker (or explicitly decide it is not persistent canon).

## Definition of done (minimum viable)

At minimum, `spec/continuity/` should include:
- A list of key state variables that must not reset (with owner/allowed transitions)
- Knowledge boundaries for major secrets (who knows what; how/when it can change)
- Invariants that must not be contradicted across chapters
- Update rules for the top variables that drive consequences

## What belongs here (and what doesn’t)

Belongs in `spec/continuity/`:
- state variables that must be tracked across chapters (injury, debt, access, ownership, relationships, mission progress)
- knowledge boundaries and reveal state (who knows what, when)
- invariants and “cannot revert without explanation” rules
- continuity checklists and common pitfall lists (high-level)

Does **not** belong in `spec/continuity/`:
- raw timeline anchors → `spec/timeline/`
- detailed plot beats → outline/fine-outline
- full character profiles → `spec/characters/` (but link to them)

## Outputs

- Spec entry files under `spec/continuity/` (one tracker/ruleset per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/continuity-entry.md` as the default structure.

## How to write continuity entries

- Prefer lists of variables + “update rules” over prose.
- Keep ownership and knowledge states explicit.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on continuity state (injury, knowledge, ownership, access), add an anchor `@spec:<id>` pointing back to the relevant continuity tracker. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Continuity Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Are tracked variables explicit enough to prevent “state reset”?
- Is who-knows-what trackable (and consistent with `spec/narrative/`)?
- Are timeline anchors mistakenly stored here instead of in `spec/timeline/`?
