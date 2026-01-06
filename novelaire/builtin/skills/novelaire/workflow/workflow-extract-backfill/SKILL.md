---
name: workflow-extract-backfill
description: After brainstorming, route confirmed decisions into the correct spec domain and produce reviewable spec proposals (one entry per id) by loading the domain skill and following its template, then apply only after explicit approval.
---

# workflow-extract-backfill

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The user explicitly confirms decisions and wants them to become canon (e.g., “定稿/拍板/写进设定/作为硬规则/以后都按这个来”).
- A conversation produced concrete constraints (rules/boundaries/costs/exceptions/terms/numbers/relationships/time anchors), and you need to prevent drift before moving downstream.
- You are about to move from spec → outline (or outline → fine-outline) and some upstream truths are only in chat/drafts.

## Quick start

1) Collect candidate facts/constraints from the conversation or `drafts/` notes.
2) Classify each item as **confirmed** vs **not confirmed**.
3) For each confirmed item, choose the correct spec domain (premise/world/system/characters/factions/locations/timeline/narrative/style/objects/glossary/continuity/serialization/quality/modules).
4) Load the domain skill and follow its template:
   - `skill__load(name="spec-...")` to get domain rules
   - `skill__read_file(name="spec-...", path="assets/templates/...")` to get the exact format
5) Create a spec proposal with `spec__propose` (one entry per id; use the domain’s template).
6) Present the proposals to the user; apply with `spec__apply` only after approval.

## Purpose

This skill turns decisions into canon safely and consistently.

It exists to:
- prevent drift (canon lives in `spec/`, not in chat)
- keep spec entries small, reusable, and domain-correct
- preserve a reviewable diff via `spec__propose`

## Output

- One or more spec proposals (`spec__propose` calls), each producing a diff artifact.
- After user approval, applied spec updates under `spec/**`.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing spec entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff for each entry.
- Apply only after explicit user approval via `spec__apply`.
- If spec is sealed, `spec__apply` will be blocked; you may still propose, but you must not attempt to apply.

## Domain routing map (what to load, where to write, which template to follow)

When extracting, **always** route each confirmed item into exactly one of these domains and use the corresponding skill template.

- `spec-premise` → writes under `spec/premise/` → template: `assets/templates/premise-core.md`
- `spec-world` → `spec/world/` → `assets/templates/world-entry.md`
- `spec-system` → `spec/system/` → `assets/templates/system-rule.md`
- `spec-characters` → `spec/characters/` → `assets/templates/character-entry.md`
- `spec-factions` → `spec/factions/` → `assets/templates/faction-entry.md`
- `spec-locations` → `spec/locations/` → `assets/templates/location-entry.md`
- `spec-objects` → `spec/objects/` → `assets/templates/object-entry.md`
- `spec-timeline` → `spec/timeline/` → `assets/templates/timeline-entry.md`
- `spec-continuity` → `spec/continuity/` → `assets/templates/continuity-entry.md`
- `spec-narrative` → `spec/narrative/` → `assets/templates/narrative-rules.md`
- `spec-style` → `spec/style/` → `assets/templates/style-profile.md`
- `spec-serialization` → `spec/serialization/` → `assets/templates/serialization-profile.md`
- `spec-quality` → `spec/quality/` → `assets/templates/quality-gate.md`
- `spec-glossary` → `spec/glossary/` → `assets/templates/term-entry.md`
- `spec-modules` → `spec/modules/<name>/` → `assets/templates/module-entry.md`

If an item mixes domains, split it into multiple entries (one per domain).

## Template note (important)

Domain templates may contain a sample YAML frontmatter block (e.g., `id:` / `title:`). When using `spec__propose`, do **not** copy that frontmatter into the `body` field:
- Put the stable id in `spec__propose.id`
- Put the human title in `spec__propose.title` (optional but recommended)
- Use only the template’s section structure as the `body`

## Routing rules

The domain skill is not optional. For each spec entry you propose:
- Load the domain skill (`skill__load`) and obey its “what belongs here” guidance.
- Read and follow the domain template (`skill__read_file`).
- Prefer stable ids with a domain prefix, e.g.:
  - `premise/core`, `world/…`, `system/…`, `characters/…`, `factions/…`, `locations/…`, `timeline/…`, `narrative/…`, `style/…`, `objects/…`, `glossary/…`, `continuity/…`, `serialization/core`, `quality/…`, `modules/<module>/…`

## Update vs create

- If a relevant entry already exists, prefer updating that id (keep ids stable across revisions).
- Before creating a new id, run `spec__query` with obvious aliases/keywords to avoid duplicate canon.

## Constraints

- Do not include “source citations” inside spec entries.
- Keep one entry = one object or one rule.
- If something is not confirmed, keep it in drafts and turn it into an open question instead of spec.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Do not use when

- The user is still exploring and has not confirmed anything as canon yet (use `workflow-brainstorm-capture`).
- The user is asking to write/modify outline/fine-outline/chapters (use the corresponding workflow skills).

## References

- Minimal extraction questions: `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`

## Self-check

- Did you keep only confirmed items in spec proposals?
- Are ids stable and correctly prefixed for paths under `spec/`?
- Are entries domain-correct and small enough to reuse?
- Did every entry follow its domain template (not an improvised format)?
