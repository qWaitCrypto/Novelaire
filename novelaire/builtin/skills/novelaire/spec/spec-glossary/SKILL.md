---
name: spec-glossary
description: Define and maintain terminology and naming discipline under spec/glossary/ (definitions, disambiguation, required/forbidden names). Use to reduce ambiguity and keep terms consistent across outline/chapters.
---

# spec-glossary

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- Terms/names are ambiguous or drifting (multiple spellings, inconsistent translations, overloaded terms).
- The system/world introduces jargon that must be defined for fair reading.
- Confusion is showing up in outline/fine-outline because terms are not fixed.

## Quick start

1) Read existing `spec/glossary/` entries and summarize confirmed terms + required naming.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/term-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep terms **unambiguous** and **enforceable** (what to call it, what not to call it).

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/glossary/` is the **ambiguity killer**: it turns words into controlled objects so the project doesn’t drift into inconsistent naming or reader confusion.

It exists to:
- prevent term drift (multiple names for the same thing)
- disambiguate near-synonyms and overloaded terms
- keep translator-friendly, reader-friendly consistency

## Module contract (Owns / Requires / Provides)

**Owns**
- Canon naming and definitions: what to call something, what not to call it, and what it means (briefly).

**Does not own**
- Worldbuilding essays → `spec/world/`
- System mechanics details → `spec/system/`
- Style/voice rules → `spec/style/`

**Requires (upstream)**
- Draws from whatever modules introduce jargon (world/system/factions/objects/characters). If a term is not canon yet, don’t lock it in.

**Provides (downstream)**
- Consistent terminology for outline/fine-outline/chapters (and easier search/revision).

## Definition of done (minimum viable)

For each term that risks confusion, the entry should include:
- Canonical name(s) and disambiguation (“this is not X”)
- Short operational definition (1–3 sentences)
- Required/forbidden naming notes only when needed (to prevent drift)

## What belongs here (and what doesn’t)

Belongs in `spec/glossary/`:
- key terms and definitions (concepts, organizations, ranks, tech/magic names, UI terms)
- required naming conventions and forbidden names (when necessary)
- disambiguation notes (what this term is not; related terms)

Does **not** belong in `spec/glossary/`:
- full worldbuilding essays → `spec/world/`
- long style manuals → `spec/style/` / technique skills
- plot beats → outline

## Outputs

- Spec entry files under `spec/glossary/` (one term per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/term-entry.md` as the default structure.

## How to write glossary entries

- Keep definitions short and operational.
- Prefer “use X in these contexts” over endless prose.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a term definition or naming constraint, add an anchor `@spec:<id>` pointing back to the relevant glossary entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Glossary Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Would a reader consistently understand the term from this entry?
- Are required/forbidden names explicit where ambiguity causes drift?
- Are you keeping definitions short instead of writing worldbuilding essays?
