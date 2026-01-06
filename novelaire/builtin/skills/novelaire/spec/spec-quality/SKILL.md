---
name: spec-quality
description: Define and maintain quality gates and checklists under spec/quality/ (what “done” means, pass/warn/fail criteria, regression check items). Use to make progress measurable and gate downstream writing work.
---

# spec-quality

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- You need to define “done” as operational PASS/WARN/FAIL gates for spec/outline/fine-outline/chapter.
- The team keeps revisiting the same quality arguments; you want a stable checklist.
- You want consistent regression criteria for long-form work.

## Quick start

1) Read existing `spec/quality/` entries and summarize confirmed quality gates and checklists.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/quality-gate.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep criteria **operational**: PASS/WARN/FAIL, not “write better”.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/quality/` is the **definition of done** layer: it turns subjective “quality” into checkable gates that can be applied to spec/outline/fine-outline/chapters.

It exists to:
- make progress measurable and reversible
- reduce rework by catching drift upstream
- standardize what to check during regression reviews

## Module contract (Owns / Requires / Provides)

**Owns**
- Operational PASS/WARN/FAIL criteria, thresholds, and regression checklists (what “done” means).

**Does not own**
- The output artifacts themselves (spec/outline/chapters).
- Long process manuals; keep gates short and checkable.

**Requires (upstream)**
- Draws constraints from other modules (premise/world/system/characters/narrative/style/etc.). If those are missing, quality gates must stay high-level.

**Provides (downstream)**
- A consistent standard for verification (including future verifier subagents/gates).
- A stable checklist that prevents repeated arguments and repeated rework.

## Definition of done (minimum viable)

At minimum, `spec/quality/` should define:
- A gate/checklist for each major artifact stage you actually use (spec, outline, fine-outline, chapter)
- The top rework risks as checkable criteria (continuity drift, premise drift, system cheating, style drift)
- Any stable thresholds you’ve committed to (only if they’re truly project-level rules)

## What belongs here (and what doesn’t)

Belongs in `spec/quality/`:
- gate definitions (PASS/WARN/FAIL criteria)
- checklists for common failure modes (continuity, premise drift, system cheating, style drift)
- thresholds (e.g., fine-outline minimum length) when they are stable project rules

Does **not** belong in `spec/quality/`:
- the output artifacts themselves (outline/chapters)
- huge process manuals

## Outputs

- Spec entry files under `spec/quality/`, each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/quality-gate.md` as the default structure.

## How to write quality entries

- Write the minimum set of gates that prevent expensive downstream rework.
- Keep gates stable; adjust only when the project’s standards change.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline decisions depend on quality thresholds, add an anchor `@spec:<id>` pointing back to the relevant quality entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Quality Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`
- Optional writing requirements (ported reference): `references/REQUIREMENTS_INDEX.md`
- Requirement detection references (ported):
  - `references/REQUIREMENT_DETECTOR_KEYWORDS.md`
  - `references/REQUIREMENT_DETECTOR_CONFLICT_RESOLUTION.md`
  - `references/REQUIREMENT_DETECTOR_EXAMPLES.md`

## Self-check

- Are criteria checkable (and not just “be good”)?
- Do gates map to the biggest rework risks?
- Are thresholds stable and appropriate for the project?
