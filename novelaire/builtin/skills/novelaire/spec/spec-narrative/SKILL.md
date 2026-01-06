---
name: spec-narrative
description: Define and maintain narrative discipline under spec/narrative/ (POV rules, knowledge boundaries, info release, forbidden shortcuts, content red lines). Use to prevent “cheating” narration and stabilize reader experience.
---

# spec-narrative

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- POV/knowledge discipline needs to be fixed (head-hopping, spoilers, “as you know” exposition).
- The user defines narrative red lines (what must not be done) or POV rules.
- You need stable info-release rules before outlining mystery/suspense.

## Quick start

1) Read existing `spec/narrative/` entries and summarize confirmed POV/knowledge boundaries and information discipline.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/narrative-rules.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep rules **enforceable**: you should be able to say “allowed / not allowed”.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/narrative/` is the **reader experience control panel**: it prevents narration from using unfair shortcuts (head-hopping, omniscient spoilers, hard exposition dumps) to solve problems.

It exists to:
- keep suspense/payoff fair and earned
- stabilize POV and knowledge boundaries
- define what narrative devices are allowed or prohibited

## Module contract (Owns / Requires / Provides)

**Owns**
- Narrative discipline: POV model, knowledge boundaries, information release rules, forbidden shortcuts, red lines.
- “Fairness” constraints for suspense/mystery: what cannot be revealed early; what cannot be stated outright.

**Does not own**
- Prose voice/texture preferences → `spec/style/`
- World facts → `spec/world/`
- Plot beats and reveal schedule as a chapter list → outline/fine-outline (narrative only constrains *how* reveals can happen)

**Requires (upstream)**
- Preferably `spec/premise/` so POV and reveal discipline match the reader promise.
- If a module relies on fairness (mystery/progression/romance beats): `spec/modules/<name>/` may add additional narrative constraints.

**Provides (downstream)**
- Constraints that every chapter must obey (what the narrator can/cannot know, how information can be released).
- Guardrails that prevent “cheating” solutions via narration.

## Definition of done (minimum viable)

At minimum, `spec/narrative/` should make these unambiguous:
- POV model (single/multi; switching rules; distance/closeness)
- Knowledge boundaries (what the narrator can state; what must be shown instead)
- Information release rules (what must not be explained early; anti-exposition shortcuts)
- Any hard red lines (content or technique) the project must not cross

## What belongs here (and what doesn’t)

Belongs in `spec/narrative/`:
- POV rules (single/multi POV; switching rules; viewpoint closeness)
- knowledge boundaries (what the narrator can/cannot know; when internal thoughts are allowed)
- information release discipline (reveal cadence; what must not be stated early)
- forbidden narrative shortcuts (e.g., omniscient answers, deus ex exposition)
- content red lines (if needed; otherwise keep minimal)

Does **not** belong in `spec/narrative/`:
- writing voice style details → `spec/style/` (or skills)
- world facts and institutions → `spec/world/`
- plot beat lists → outline/fine-outline

## Outputs

- Spec entry files under `spec/narrative/` (one ruleset per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/narrative-rules.md` as the default structure.

## How to write narrative rules

- Write rules as constraints, not advice: “Do X / Don’t do Y.”
- Keep rules minimal: only what must be stable across the whole project.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a narrative constraint (POV switch, reveal timing, what cannot be stated), add an anchor `@spec:<id>` pointing back to the relevant narrative rules. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Narrative Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`
- Optional: for broad story/voice frameworks, load `workflow-outline` and use its `references/FRAMEWORKS_*.md`.

## Self-check

- Can you judge “allowed vs cheating” narration from these rules alone?
- Are POV and knowledge boundaries stable enough to prevent leaks?
- Did you accidentally mix stylistic preferences into hard narrative discipline?
