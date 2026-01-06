---
name: spec-factions
description: Define and maintain factions/organizations canon under spec/factions/ (goals, resources, methods, boundaries, relationships, reaction patterns). Use when plot needs structural pressure and consequences.
---

# spec-factions

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The plot needs structural pressure and consequences (institutions, gangs, agencies, guilds).
- Actions feel consequence-free because “the world doesn’t push back”.
- You need stable faction reactions to constrain outline beats.

## Quick start

1) Read existing `spec/factions/` entries and summarize confirmed faction goals/resources/boundaries.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/faction-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **actionable**: what the faction can do, will do, and cannot do.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/factions/` is the **structural pressure layer**: it makes consequences real by defining who can mobilize what power, through what levers, with what limits.

It exists to:
- prevent “villain of the week” randomness
- make escalation coherent (actions trigger institutional reactions)
- keep politics/resources consistent across arcs

## Module contract (Owns / Requires / Provides)

**Owns**
- Faction-level behavior and constraints: goals, levers, resources, typical methods, boundaries, reaction patterns.

**Does not own**
- World baseline institutions/history → `spec/world/`
- System mechanics → `spec/system/`
- Character inner truth/arc → `spec/characters/` (factions can reference roles/affiliations)

**Requires (upstream)**
- Usually `spec/world/` (institutions, enforcement, scarcity) to keep faction power plausible.
- If the faction uses powers/tech: `spec/system/` to avoid “infinite capability” drift.

**Provides (downstream)**
- Predictable consequences and escalation pressure for outline/fine-outline/chapters.

## Definition of done (minimum viable)

For each major faction that will drive plot pressure, the entry should state:
- Goal/agenda (what they want *now* and long-term)
- Levers/resources (what they can do) + limits (what they cannot do)
- Reaction pattern (what happens when threatened/exposed/insulted)
- Key relationships (allies/rivals/internal fractures) that shape decisions

## What belongs here (and what doesn’t)

Belongs in `spec/factions/`:
- faction purpose/ideology and concrete goals
- resources, influence, reach, and typical methods
- boundaries and constraints (what they won’t do; what they cannot do; internal fractures)
- relationships with other factions and key characters
- reaction patterns: what reliably happens when they are threatened/exposed

Does **not** belong in `spec/factions/`:
- world baseline institutions and history → `spec/world/`
- system mechanics for “powers” → `spec/system/`
- detailed plot beats (“they attack in chapter 9”) → outline/fine-outline

## Outputs

- Spec entry files under `spec/factions/` (one faction per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/faction-entry.md` as the default structure.

## How to write faction entries

- Prefer levers (“they can freeze accounts / arrest / blockade / smear”) over vague descriptions.
- Define constraints so the faction can’t solve everything instantly.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on faction pressure or consequences, add an anchor `@spec:<id>` pointing back to the relevant faction entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Factions Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Can you predict how the faction responds to threats from this entry alone?
- Are their levers + limits explicit enough to prevent “plot convenience”?
- Are relationships and internal constraints clear enough to generate conflict?
