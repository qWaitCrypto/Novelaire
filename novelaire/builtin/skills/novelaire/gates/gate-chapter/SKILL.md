---
name: gate-chapter
description: Run the Chapter Gate (PASS/WARN/FAIL) after drafting a chapter. Use to ensure chapter obeys its fine-outline results and doesn’t contradict upstream canon.
---

# gate-chapter

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- A chapter was drafted or revised and you need to decide whether to continue to the next chapter.
- The user reports “写着写着偏了/不太对劲/逻辑有问题” after drafting.
- You are about to backfill spec/outline based on what was written and need to confirm what is actually consistent.

## What this gate protects

This gate prevents “quiet drift” at the prose layer by checking:
- the chapter still matches its fine-outline (key beats + end state)
- no rule cheating (system/world/continuity violations)
- no accidental knowledge leaks (POV boundaries)

## Quick start

1) Read the chapter file under `chapters/` (or project-defined chapter location).
2) Read the corresponding chapter fine-outline plan.
3) Check compliance:
   - key events and end state match the plan
   - no major contradictions with existing chapters/outline/spec
4) Output a Gate Report.

## Inputs (what to read)

- The chapter file under project `chapters/`.
- The corresponding chapter plan in fine-outline:
  - preferred: per-chapter file under `outline/fine/`
  - acceptable: a chapter section inside `outline/fine-outline.md`
- Relevant constraints: `spec/continuity/*`, `spec/system/*`, `spec/timeline/*` (as needed)

## Evidence tooling (how to stay concrete)

- Use `project__glob` to locate the chapter file and fine-outline files.
- Use `project__search_text` to find the chapter’s section heading in `outline/fine-outline.md` (if monolithic).
- Use `project__read_text` / `project__read_text_many` to quote plan beats and the corresponding prose passage.
- Use `project__search_text` to anchor findings to line numbers (keywords, names, `@spec:` anchors).

## Fix routing (where to repair)

- Chapter deviates from fine-outline but the new direction is desired → revise fine-outline (and possibly outline) to match, then re-run this gate.
- Chapter deviates unintentionally → revise chapter prose to match the plan, not the other way around.
- Chapter violates spec constraints → fix upstream first (fine-outline/outline/spec), then revise chapter as needed.

## Gate Report format

- **Target**: Chapter
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / revise chapter / revise fine-outline / revise outline/spec

## Minimum checks (v1)

PASS:
- Chapter follows its fine-outline key events and end result (prose details may vary).
- No contradictions with existing chapters/outline/key spec.

FAIL:
- Major drift breaks mainline logic or violates rule boundaries (system/world/continuity).

## Constraints

- Do not modify chapter text while running this gate; only report findings.
- When you find a contradiction, recommend upstream-first fixes (fine-outline/outline/spec) unless the chapter is clearly at fault.
- Findings MUST be anchored to concrete text (file + line or quote).

## Self-check

- Did you recommend upstream fixes first (fine-outline/outline/spec) when contradictions appear?
