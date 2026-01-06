---
name: workflow-fine-outline
description: Produce per-chapter fine outline under outline/ that obeys spec constraints and meets minimum length (Han > 500 per chapter). Use before drafting chapters to lock causality and pacing.
---

# workflow-fine-outline

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- An outline exists (or is being requested), and the user wants to start writing chapters soon.
- Chapters are being drafted but drift is happening; you need a tighter per-chapter plan to regain control.
- The user asks for “细纲/分章细化/每章要写什么/每章目标与转折”.

## Preconditions (rigor)

- If there is no outline yet, run `workflow-outline` first (and pass `gate-outline`).
- If critical constraints are still missing (e.g., system costs/limits), backfill spec via `workflow-extract-backfill` + `spec-*`.
- If `outline/outline.md` contains an “Undecided / Open Questions” list, do not ignore it; carry those items forward and resolve them upstream before drafting chapters.

## Quick start

1) Read the current outline (`outline/outline.md`) and relevant spec constraints.
2) Produce a per-chapter fine outline using the skill template `assets/templates/fine-outline-chapter.md`.
3) Ensure each chapter’s fine-outline section is **Han > 500** (use `project__text_stats` to verify after writing).
4) Write to the **project working directory** `outline/fine-outline.md` (or one file per chapter under project `outline/fine/` if the project uses that layout).
5) Run `gate-fine-outline` and output a Gate Report before drafting chapters.

## Purpose

This skill locks down chapter-level causality and constraints before prose.

It exists to:
- reduce downstream rewrites by catching drift early
- make each chapter’s intent, conflict, and payoff explicit
- enforce a minimum information density per chapter plan

## Output

- Fine outline Markdown under `outline/fine-outline.md` (or per-chapter files).
- Each chapter fine-outline block MUST include:
  - goal/obstacle/stakes
  - key beats (cause → effect)
  - constraint anchors (`@spec:<id>`) where relevant
  - planned hook/payoff (as needed by serialization)

## Constraints

- Fine-outline MUST obey spec constraints (premise/system/continuity).
- Minimum length rule: **Han > 500 per chapter**.
- Do not write prose paragraphs; write plan-level content.
- Do not “solve” undecided constraints inside chapter prose. If a chapter plan depends on a missing rule/fact, mark it as undecided and backfill upstream (spec/outline/fine-outline) first.
- Do not write fine-outline artifacts into this skill directory; `assets/` is for templates only.

## References

- Common fine-outline pitfalls + fixes: `references/PITFALLS.md`
- Optional: for broader structure frameworks, load `workflow-outline` and use its `references/FRAMEWORKS_*.md`.

## Self-check

- Does each chapter have clear goal/obstacle/stakes and causal beats?
- Are anchors used where constraints matter?
- Did you verify Han > 500 for each chapter plan?
- Did you run `gate-fine-outline` and address FAIL/WARN before drafting?
