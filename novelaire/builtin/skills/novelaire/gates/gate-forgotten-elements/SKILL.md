---
name: gate-forgotten-elements
description: Run the Forgotten Elements Gate to find dropped characters, stalled plot threads, and uncollected foreshadowing in long-form fiction, then output a prioritized fix list.
---

# gate-forgotten-elements

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The story is getting longer (multi-arc / serialized) and elements may have been dropped.
- The user asks “有没有哪些伏笔/角色/支线忘了？” or “是不是有烂尾/弃坑感？”.
- You are preparing a milestone regression and want to catch “missing threads” early.

## Quick start

1) Choose a chapter range (e.g. last 10 chapters, an arc, or the whole book so far).
2) Build the “elements to track” list (characters, plot threads, foreshadowing anchors) from `spec/`, outline/fine-outline, or a user-provided list.
3) Scan `chapters/` to find each element’s most recent appearance / progress.
4) Report elements that exceed the configured “missing” thresholds.
5) Output a Gate Report.

## Evidence tooling (how to stay concrete)

- Build the tracking list with aliases:
  - For a character: name + common aliases/nicknames.
  - For a thread/foreshadowing: a short tag + 2–5 distinct keywords that should appear when it advances.
- Use `project__search_text` over `chapters/` for each element keyword to find last-seen chapter + line numbers.
- If the element comes from a spec entry, include the `@spec:<id>` in the finding as the constraint anchor.

## Gate Report format

- **Target**: Forgotten elements
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / plan reinsertion / mark as retired / revise outline

## References

- Checklist + thresholds + examples: `references/FORGOTTEN_ELEMENTS.md`

## Constraints

- Do not modify story files while running this gate; only report findings.
- Distinguish “retired by design” (intentionally ended) vs “dropped by accident” (needs reinsertion).

## Fix routing (where to repair)

- If an element should return/advance → plan reinsertion in fine-outline first (preferred), then revise chapters.
- If an element is intentionally retired/paused → record that upstream (outline/fine-outline, optionally spec/continuity) so future scans don’t re-flag it.
- If the “missing” is actually acceptable pacing (slow burn) → downgrade severity and set a planned checkpoint (“touch again by Chapter X”).

## Self-check

- Are “missing” flags based on a concrete scan (mentions/anchors), not guesswork?
- Did you distinguish “retired by design” vs “dropped by accident”?
