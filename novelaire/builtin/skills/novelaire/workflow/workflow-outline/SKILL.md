---
name: workflow-outline
description: Produce a high-level outline under outline/ that obeys spec constraints and uses @spec:<id> anchors at key ambiguity points; proactively use when spec is ready and the user wants a story spine (acts/arcs/chapter list) without writing prose yet.
---

# workflow-outline

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user wants a story spine (大纲/主线/三幕/章节列表/分卷分幕) but does not want prose yet.
- Spec decisions are already confirmed (premise + key system/world constraints exist), and the next step is structure.
- The user is about to start drafting chapters without a stable outline (risk of drift).

## Preconditions (rigor)

- Spec MUST be usable (at least premise + key system constraints). If not, run `gate-spec` and/or use `workflow-extract-backfill` + `spec-*` skills to backfill spec first.
- If the user is still exploring and undecided, use `workflow-brainstorm-capture` first.

## Quick start

1) Read relevant spec entries (use `spec__query` / `spec__get` and load specific ids as needed).
2) Choose an outline granularity appropriate for the user (acts/parts + chapter list, or arc list).
3) Draft the outline in-chat for confirmation.
4) Write the outline to `outline/outline.md` using `assets/templates/outline.md`.
5) Run `gate-outline` and output a Gate Report before moving to fine-outline.

## Purpose

This skill creates a structure that is constrained by canon but still flexible.

It exists to:
- turn spec constraints into a coherent story spine
- prevent premise drift and system-cheating solutions at outline time
- set up fine-outline and chapters without overcommitting to prose

## Output

- A Markdown outline file in `outline/outline.md` (or project-chosen outline path).
- Include `@spec:<id>` anchors at key ambiguity points (constraints, not provenance).
- Keep an explicit “Undecided / Open Questions” list for anything that is not yet canon (so it doesn’t silently drift).

## Constraints

- The outline MUST obey `spec/` constraints, especially premise and system fairness.
- Do not write prose; write structure.
- Do not put the outline into `spec/`.
- If an outline beat requires a missing core constraint, do not invent it; instead:
  - mark it as undecided in the outline, and
  - backfill spec via `workflow-extract-backfill` / `spec-*` before proceeding.

## References

- Common outline pitfalls + fixes: `references/PITFALLS.md`
- Story structure frameworks (ported reference): `references/FRAMEWORKS_STRUCTURES.md`
- Character + voice frameworks (ported reference): `references/FRAMEWORKS_CHARACTER_VOICE.md`
- Scene construction + quality checklists (ported reference): `references/FRAMEWORKS_SCENE_QUALITY.md`

## Self-check

- Do major turns map to the reader promise and conflict spine?
- Are solutions inside system limits (no author fiat)?
- Are anchors used where a constraint matters?
- Did you run `gate-outline` and address FAIL/WARN before proceeding?
