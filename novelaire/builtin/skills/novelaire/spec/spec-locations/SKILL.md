---
name: spec-locations
description: Define and maintain reusable locations canon under spec/locations/ (purpose, stable details, access rules, dangers, constraints, navigation). Use when scenes reuse places or when space rules cause continuity errors.
---

# spec-locations

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- A place will be reused across scenes and must stay consistent (layout, access rules, danger).
- Travel/access logic is causing contradictions (“they can’t be here”, “security makes no sense”).
- You need clear entry/exit constraints to constrain scene planning.

## Quick start

1) Read existing `spec/locations/` entries and summarize confirmed location rules/stable details.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/location-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries **reusable** and **continuity-safe** (stable details + access rules).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/locations/` is the **reusability + continuity layer** for places: the same location should not “change skin” between chapters, and its rules should constrain action.

It exists to:
- prevent spatial continuity errors (layouts, access, travel time, security)
- make scenes feel grounded (stable sensory + functional details)
- encode “place rules” that create tension (dangers, constraints, entrances/exits)

## Module contract (Owns / Requires / Provides)

**Owns**
- Reusable locations and their stable constraints: layout anchors, access rules, dangers, entry/exit logic.

**Does not own**
- Broad geography/culture baselines → `spec/world/`
- Security/power mechanics → `spec/system/` (locations can reference them)
- Who controls the place → `spec/factions/` (locations reference ownership/access policy)

**Requires (upstream)**
- Usually `spec/world/` for travel/communication plausibility.
- Often `spec/factions/` for access rules and enforcement.

**Provides (downstream)**
- Spatial constraints that make scenes believable and prevent “teleporting rules”.

## Definition of done (minimum viable)

For any location that will recur, the entry should include:
- Stable anchors (what the reader can picture consistently)
- Entry/exit and access rules (who can enter, how, what checks)
- Consequences/dangers (what triggers escalation)
- Navigation constraints if relevant (chokepoints, surveillance, blind spots)

## What belongs here (and what doesn’t)

Belongs in `spec/locations/`:
- a reusable place and its stable facts (layout, key landmarks, typical crowd, security)
- access/entry rules (who can enter, how, what checks exist)
- dangers/limitations (what you cannot do there; what triggers consequences)
- navigation anchors (entrances/exits, chokepoints, surveillance blind spots if relevant)

Does **not** belong in `spec/locations/`:
- broad geography/culture baselines → `spec/world/`
- system mechanics powers → `spec/system/`
- plot beats for a single chapter → outline/fine-outline

## Outputs

- Spec entry files under `spec/locations/` (one location per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/location-entry.md` as the default structure.

## How to write location entries

- Encode constraints: “cannot do X here because…; if Y then consequence Z”.
- Keep stable details small but consistent (useful for reuse).
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on location rules (access, danger, travel, security), add an anchor `@spec:<id>` pointing back to the relevant location entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Locations Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Could you reuse this location in multiple chapters without contradictions?
- Are access rules and consequences explicit enough to constrain action?
- Did you accidentally record a one-off scene beat instead of stable place canon?
