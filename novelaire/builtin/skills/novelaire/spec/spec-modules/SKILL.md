---
name: spec-modules
description: Enable and maintain optional mechanism sub-specs under spec/modules/<name>/ (mystery/romance/progression/etc.). Use when a story actually uses a module; avoid creating modules by default.
---

# spec-modules

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The story uses a specific “module” mechanism (mystery/romance/progression/system UI/etc.) that needs explicit fairness rules.
- The user requests module-specific discipline (e.g., “推理要公平/恋爱要按某种节奏/升级要有边界”).
- Regression is repeatedly finding the same module drift (cheating mysteries, unbounded progression, sloppy romance beats).

## Quick start

1) Confirm which module(s) the story truly needs (do not create modules by default).
2) Read existing `spec/modules/*` entries (if any) and summarize what’s confirmed.
3) If missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
4) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/module-entry.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/modules/<name>/` is an **opt-in constraints layer** for specific genre/story mechanisms (mystery, romance, progression, system UI, transmigration, etc.).

It exists to:
- prevent “module drift” (cheating mysteries, sloppy romance beats, unbounded progression)
- keep module-specific fairness rules explicit
- avoid spec bloat by only enabling what’s used

## Module contract (Owns / Requires / Provides)

**Owns**
- Opt-in mechanism discipline: scope, fairness/anti-cheat rules, boundaries, and checkable constraints for a specific module.

**Does not own**
- Core canon (premise/world/system/characters) → link instead of duplicating.
- The outline itself → `outline/`

**Requires (upstream)**
- Usually `spec/premise/` and `spec/narrative/` so “fairness” matches the reader promise and POV rules.
- If the module relies on mechanisms (progression/system UI): `spec/system/`.

**Provides (downstream)**
- Extra constraints for outline/fine-outline/chapters that preserve reader trust for that module.

## Definition of done (minimum viable)

For each enabled module, the spec should state:
- Scope (what this module covers, and what it explicitly does not cover)
- Fairness/anti-cheat rules (what is forbidden; what must be shown/earned)
- Boundaries and “no free lunch” constraints
- A short regression checklist (what to verify when revising)

## What belongs here (and what doesn’t)

Belongs in `spec/modules/<name>/`:
- module scope and enablement conditions
- core rules/discipline (fairness constraints, boundaries, anti-cheat)
- module-specific regression checks (high level)

Does **not** belong in `spec/modules/<name>/`:
- global premise/world/system canon (link instead)
- broad style guides

## Outputs

- Module entry files under `spec/modules/<name>/` (one rule/object per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/module-entry.md` as the default structure.

## How to write module entries

- Keep modules narrow: define what you must constrain to keep fairness and reader trust.
- Prefer checkable constraints over vibe guidance.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a module constraint, add an anchor `@spec:<id>` pointing back to the relevant module entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Modules Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Are modules only enabled when the story needs them (no default bloat)?
- Are module-specific fairness rules explicit and enforceable?
- Are module entries small and reusable (not an outline)?
