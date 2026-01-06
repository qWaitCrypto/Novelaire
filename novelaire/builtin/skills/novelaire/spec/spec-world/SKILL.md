---
name: spec-world
description: Define and maintain world facts and hard constraints under spec/world/ (society, geography, history, resources, baseline reality). Use when establishing worldbuilding/世界观 (社会结构/地理/历史/资源), or when plot/scene causality drifts against world reality.
---

# spec-world

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user is establishing worldbuilding/世界观 (社会结构/地理/历史/资源/常识边界).
- Plot/scene causality drifts against world reality (travel times, institutions, scarcity, norms).
- The outline introduces “world facts” that will be reused and must not drift.

## Quick start

1) Read existing `spec/world/` entries and summarize confirmed constraints.
2) If missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/world-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep entries stable and constraint-oriented (no plot beats; no system mechanics rules).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/world/` is the **reality layer**: stable facts and constraints that make scenes and causality believable.

It exists to lock down:
- How the world operates (society, economy, culture, geography, history, daily life baselines)
- What is *not possible* / not reasonable in this world
- Resource ceilings and institutional realities that shape character choices

It prevents “ad-hoc worldbuilding” where the world bends per scene convenience.

## What belongs here (and what doesn’t)

Belongs in `spec/world/`:
- World-level facts that many scenes depend on (laws, norms, infrastructure, scarcity, distances, climate, social structure)
- Background history that constrains the present (wars, collapses, reforms, founding myths that actually affect behavior)
- Hard constraints: what cannot happen; what has unavoidable consequences

Does **not** belong in `spec/world/`:
- Specific character truths → `spec/characters/`
- Mechanics rules (magic/tech/power systems) → `spec/system/`
- Specific reusable places and their entry/danger rules → `spec/locations/`
- Exact plot beats / chapter plans → `outline/` and fine-outline

## Module contract (Owns / Requires / Provides)

**Owns**
- Baseline reality: institutions, norms, scarcity, distances, infrastructure, daily-life constraints, “how things usually work”.
- World-level constraints that many scenes depend on (and that must not bend per-scene).

**Does not own**
- System mechanics (how powers/tech work) → `spec/system/`
- Specific reusable locations → `spec/locations/`
- Organization/faction behavior → `spec/factions/` (world can define the *type* of institution; factions define specific actors)

**Requires (upstream)**
- Preferably `spec/premise/` so world tone/realism aligns with the reader promise.
- If `spec/system/` exists, world entries must reflect its second-order consequences (institutions, economics, norms).

**Provides (downstream)**
- Causality constraints for outline/fine-outline/chapters (what is plausible; what triggers consequences).
- Ground truth for factions/locations/timeline (travel/communication baselines, enforcement, scarcity).

**Routing rule**
- If a “world fact” is introduced while working on factions/locations/objects, backfill it here as a stable entry (or explicitly mark it as not-canon yet).

## Definition of done (minimum viable)

At minimum, `spec/world/` should cover the handful of constraints that will be reused constantly:
- Institutions & enforcement (who can punish/permit/ban)
- Scarcity & infrastructure (what is hard/expensive/rare; what is easy/cheap/abundant)
- Travel/communication baselines (what takes time; what is instant; what is monitored)
- Social norms & taboos (what causes reputation loss, violence, legal risk)
- Geography/space constraints if the story depends on them

## Outputs

- Spec entry files under `spec/world/` (one entry per object/rule), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/world-entry.md` as the default structure.

## How to write world entries

- Prefer concrete constraints (“X cannot happen because…”, “If Y happens, consequence Z follows”) over atmosphere-only text.
- Avoid mixing multiple unrelated facts into one file; keep entries small and reusable.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a world constraint (resources, institutions, plausibility, travel/communication), add an anchor `@spec:<id>` pointing back to the relevant world entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- World Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check
- Would a reader accept scene causality given these world constraints?
- Are any “rules” actually system mechanics that should move to `spec/system/`?
- Are you accidentally writing plot beats instead of constraints?
