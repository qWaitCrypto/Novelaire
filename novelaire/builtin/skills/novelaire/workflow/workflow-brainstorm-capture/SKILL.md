---
name: workflow-brainstorm-capture
description: Capture exploratory discussion into the project drafts as a structured working note (confirmed vs options vs open questions) before committing anything as canon; proactively use when the user is still exploring, undecided, or asks to “note/save/brainstorm first”.
---

# workflow-brainstorm-capture

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user is exploring and explicitly says: “先脑暴/先记一下/先落盘/先保存思路/不要定稿/先别写进设定/先别写大纲”.
- There are **multiple competing options** and the user has not chosen yet.
- There are **open questions** that block downstream work, and you want to preserve the current state before asking/branching.
- The conversation produced useful constraints, but the user has not confirmed they are canon yet (so it should not go to `spec/`).
- You are about to switch phases (e.g., spec → outline) but the upstream is not ready; capture the current exploration so it doesn’t get lost.

## Quick start

1) Identify what the user is exploring (premise/world/system/characters/etc.).
2) Separate **confirmed constraints** from **hypotheses/options**.
3) Produce a clean capture note using the skill template `assets/templates/brainstorm-capture.md`.
4) Write it to the **project working directory** `drafts/brainstorm.md` (append a new section; do not overwrite past captures).

## Purpose

This skill turns messy ideation into a structured artifact **without turning it into canon**.

It exists to:
- preserve alternatives (so you don’t “lock in” too early)
- keep uncertainty explicit (no invented facts)
- create a stable input for later extraction/backfill into `spec/`

## Output

- A Markdown note in the project working directory `drafts/brainstorm.md` (or a file under project `drafts/` if the project uses per-topic notes).
- The note MUST clearly distinguish:
  - confirmed constraints
  - open questions
  - options with trade-offs

## Rules

- Do not write to `spec/` during brainstorming (unless user explicitly confirms canon decisions).
- Do not write outline/fine-outline beats here.
- Keep it short and navigable; use bullets and headings.
- If you include AI suggestions, wrap them in `<AI>...</AI>`. Use `<hidden>...</hidden>` for author-only secrets (see `references/GUIDE.md`).
- Do not write brainstorming artifacts into this skill directory; `assets/` is for templates only.

## Do not use when

- The user is asking to **finalize** and commit canon (use `workflow-extract-backfill` / spec workflow instead).
- The user is asking to **produce the actual outline/fine-outline/chapter** as an output artifact (use the corresponding workflow skills).

## References

- Minimal questions to clarify exploration: `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Brainstorming capture guide (ported reference): `references/GUIDE.md`
- Chapter planning: `references/chapter-planning.md`
- Worldbuilding: `references/worldbuilding.md`
- Character development: `references/character-development.md`
- Continuity + timeline: `references/continuity-timeline.md`

## Self-check

- Are confirmed vs hypothetical items clearly separated?
- Did you preserve multiple options rather than collapsing to one?
- Is there a short list of next decisions/questions for the user?
