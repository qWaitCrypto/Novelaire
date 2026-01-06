---
name: spec-style
description: Define and maintain style constraints under spec/style/ (voice contract, rhythm/density targets, dialogue/description balance, avoid/embrace guidelines). Use to stabilize prose voice and reduce “AI-sounding” drift.
---

# spec-style

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user wants a stable voice contract (tone/rhythm/density/balance) across chapters.
- Prose starts drifting into generic “assistant voice” / “AI-sounding” patterns.
- You need clear non-negotiables (what to avoid) before drafting chapters.

## Quick start

1) Read existing `spec/style/` entries and summarize confirmed voice constraints and non-negotiables.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/style-profile.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep it **minimal and enforceable** (a voice contract, not an encyclopedia).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/style/` is the **voice contract**: stable constraints that keep prose consistent and natural.

It exists to:
- stabilize rhythm, tone, and voice across chapters
- reduce generic “assistant voice” drift
- define non-negotiables (what the prose should not become)

## Module contract (Owns / Requires / Provides)

**Owns**
- A small, enforceable voice contract: tone/attitude, rhythm/density targets, and a short non-negotiables list.
- Stable “preferred moves” that reliably feel on-voice for this project.

**Does not own**
- POV/knowledge rules and reveal discipline → `spec/narrative/`
- Long technique manuals or phrase lists → technique skills (e.g. `tech-dialogue`, `tech-scene-structure`)
- World/system/character canon

**Requires (upstream)**
- Preferably `spec/premise/` so voice matches genre promise and emotional target.
- Preferably `spec/narrative/` so style doesn’t conflict with POV/knowledge discipline.
- If serialized constraints exist: `spec/serialization/` may influence recap/hook style (but keep it principle-level).

**Provides (downstream)**
- Constraints for drafting and revising chapters so voice stays consistent across time.
- A stable “anti-AI drift” contract: what patterns to avoid and what moves to prefer.

## Definition of done (minimum viable)

At minimum, `spec/style/` should contain one core profile (recommended id: `style/core`) that includes:
- Voice contract (tone, emotional texture, reader distance)
- Rhythm/density targets (sentence rhythm, description density, interiority amount)
- A short non-negotiables list (5–15 items; checkable)
- (Optional but strong) 1 short sample paragraph that is clearly “on-voice” (best if user-provided)

## What belongs here (and what doesn’t)

Belongs in `spec/style/`:
- voice/tone/texture constraints that should stay stable throughout the project
- density/rhythm targets (e.g., how compressed vs lyrical; how much interiority)
- dialogue/description balance preference (if stable)
- a small “avoid/embrace” list (principle-level, not a giant banlist)

Does **not** belong in `spec/style/`:
- narrative POV/knowledge rules → `spec/narrative/`
- scene-by-scene style experiments → drafts
- long style manuals and huge phrase lists (put in optional technique skills)

## Outputs

- Spec entry files under `spec/style/` (one style profile per project, or per POV voice if needed), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/style-profile.md` as the default structure.

## How to write style entries

- Write constraints you can actually check (“avoid meta-summaries”, “prefer concrete sensory details over abstract praise”).
- Keep it short; add details only when they measurably prevent drift.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline relies on a stable voice constraint (tone/rhythm/balance), add an anchor `@spec:<id>` pointing back to the style profile. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Style Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`
- Optional style guides (ported reference): `references/STYLE_GUIDES_INDEX.md`

## Self-check

- Is this a short voice contract (constraints) rather than a giant guide?
- Can you detect “AI-sounding drift” from these constraints?
- Are you mixing POV rules or plot beats into style?
