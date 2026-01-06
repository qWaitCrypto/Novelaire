---
name: spec-premise
description: Define and maintain story premise constraints under spec/premise/ (logline, core conflict spine, theme, reader promise, non-negotiables). Use when starting a story, when user asks for premise/logline/主线/主题/读者承诺, or when outline/chapters drift off-premise (偏题).
---

# spec-premise

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user asks for premise/logline/主线/主题/读者承诺/这本书“讲什么不讲什么”.
- Outline/fine-outline/chapters are drifting off-premise (偏题), or the conflict spine can’t be stated cleanly.
- You need a stable “north star” before moving to outline.

## Quick start

1) Read existing `spec/premise/` entries (if any) and summarize what is already confirmed.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/premise-core.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep premise **testable** and **stable** (no chapter beats, no world/system details).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/premise/` is the story’s **north star**. It exists to answer (and keep stable):
- What this book is *about* (and what it is not about)
- The core conflict spine (start → escalation → resolution direction)
- Theme + reader promise (what experience you are committing to deliver)
- Non-negotiable boundaries that other work must obey

`spec/premise/` is **not** where you put:
- chapter beats, outline structure, or scene plans
- detailed world/system rules (those go to `spec/world/` and `spec/system/`)

## Module contract (Owns / Requires / Provides)

**Owns**
- The book-level intent and constraints: logline, conflict spine, theme, reader promise, non-negotiables.
- The “reject list”: what this book is *not* (anti-promise).

**Does not own**
- Plot beats (outline/fine-outline), scene plans, or chapter text.
- World baselines (`spec/world/`), system mechanics (`spec/system/`), character canon (`spec/characters/`).

**Requires (upstream)**
- None strictly. If premise is missing, do not proceed to heavy outlining; ask the minimum questions first.

**Provides (downstream)**
- A stable north star used to judge: on-premise/off-premise, escalation direction, acceptable twists, and “tempting but wrong” subplot directions.
- Constraints that other spec modules must respect (world tone realism vs promise, system fairness vs promise, character arcs vs theme).

**Conflict resolution**
- If downstream modules (world/system/characters/outline) drift against premise, treat it as a WARN/FAIL unless the user explicitly updates the premise.

## Definition of done (minimum viable)

At minimum, `spec/premise/` should contain:
- One “core” entry (recommended id: `premise/core`) that includes:
  - 1-sentence logline
  - core conflict spine (opposition + escalation direction + what resolution means)
  - theme (central question/tension)
  - reader promise + anti-promise
  - non-negotiables (3–7 checkable constraints)

## Outputs

- One or more **Spec entries** as Markdown files under `spec/premise/`, each beginning with YAML frontmatter containing a stable `id`.
- Recommended first entry: create a “premise core” file (e.g. `spec/premise/core.md`) using `assets/templates/premise-core.md`.

## How to write premise entries

- Prefer short, concrete, falsifiable statements over vibe language.
- When the user is exploring, do not “finalize” into `spec/` yet—keep it in discussion/drafts until confirmed.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline hits a key ambiguity point (“is this on-premise?” / “does this violate the promise?”), add an anchor `@spec:<id>` pointing back to the relevant premise entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Premise Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Can you judge outline drift (“on-premise/off-premise”) from these entries alone?
- Is the reader promise explicit enough to reject tempting-but-wrong directions?
- Did you accidentally put world/system/character specifics here instead of their domains?
