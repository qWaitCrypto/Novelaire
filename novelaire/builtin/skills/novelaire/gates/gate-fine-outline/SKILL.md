---
name: gate-fine-outline
description: Run the Fine-outline Gate (PASS/WARN/FAIL) before drafting chapters. Enforces per-chapter structure and Han > 500 per chapter plan when measurable.
---

# gate-fine-outline

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- Fine-outline exists and you are about to draft chapters.
- Fine-outline was recently edited and you need to confirm the minimum standard (structure + Han threshold).
- Chapters are drifting; you suspect the fine-outline is too vague to control prose.

## What this gate protects

This gate prevents you from drafting chapters on top of a fine-outline that is:
- too short/vague to control prose (invites drift)
- missing end-state clarity (invites “chapter happens” without consequence)
- missing anchors at ambiguity points (invites rule cheating)
- carrying unresolved questions that will get “solved” in prose by accident

## Inputs (what to read)

- Fine-outline artifact(s) under project `outline/`:
  - preferred: `outline/fine/*.md` (one file per chapter)
  - acceptable: `outline/fine-outline.md`
- `outline/outline.md` (for intended spine and open questions)
- Relevant constraints in `spec/` (premise/system/continuity/timeline)

## Quick start

1) Locate fine-outline artifacts under `outline/`:
   - preferred: one file per chapter under `outline/fine/`
   - acceptable: a single `outline/fine-outline.md` (harder to measure per chapter)
2) For each chapter plan, verify required structure and constraints.
3) Verify **Han > 500 per chapter plan**:
   - if per-chapter files exist, use `project__text_stats` for each file and check `counts.han`
4) Output a Gate Report.

## Evidence tooling (how to stay concrete)

- Use `project__glob` to list fine-outline files.
- Use `project__text_stats` to verify `counts.han` per chapter plan (when files are per-chapter).
- Use `project__read_text` to quote missing/ambiguous sections.
- Use `project__search_text(query=\"@spec:\", path=\"outline\")` to spot-check anchors.

## Fix routing (where to repair)

- Structure too vague / missing end state → revise fine-outline, not chapter prose.
- Missing canon constraint needed by a chapter → backfill spec/outline first, then revise fine-outline.
- Han below threshold → expand stakes/obstacles/beat consequences; add explicit end state.
- Many unresolved questions → resolve upstream or mark as blocking (FAIL) if drafting depends on them.

## Gate Report format

- **Target**: Fine-outline
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / revise fine-outline / revise outline / rollback

## Minimum checks (v1)

PASS:
- Each chapter fine-outline has **Han > 500** (when measurable).
- Each chapter includes at least: goal / conflict / key turn or info gain / end state (result).
- Where ambiguity points exist, chapter plan includes constraint anchors `@spec:<id>` (when necessary).

FAIL:
- Any chapter plan is missing the “what/why/result” skeleton such that drafting can’t be controlled.

WARN:
- Han count cannot be measured reliably due to monolithic file layout; recommend splitting to per-chapter files.
- Chapter plans exist but “Undecided / Open Questions” remain; treat as WARN unless they block drafting.

## Constraints

- Do not modify `outline/` while running this gate; only report findings.
- If a chapter plan depends on missing canon constraints, recommend backfilling upstream (spec/outline), not “fix it in prose”.
- Findings MUST be anchored to concrete locations (file + heading, or file + line when available).

## Self-check

- Did you verify the >500 Han requirement using `project__text_stats` when possible?
- Are fixes targeted (revise the plan), not “fix it in prose”?
