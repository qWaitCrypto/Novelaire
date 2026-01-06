---
name: spec-serialization
description: Define and maintain serialization engineering constraints under spec/serialization/ (chapter length targets, update cadence, payoff/recap discipline, volume rhythm). Use to keep outline/fine-outline aligned to a stable release model.
---

# spec-serialization

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The project is serialized/long-form and needs stable chapter length/cadence/hook/payoff rules.
- The user specifies update cadence or target chapter length constraints.
- You need to align outline/fine-outline rhythm with a release model.

## Quick start

1) Read existing `spec/serialization/` entries and summarize confirmed release model constraints.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/serialization-profile.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep it **principle-level**: it constrains outline/fine-outline, but it is not the outline.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/serialization/` is the **release rhythm layer**: it defines the engineering parameters that shape how you structure arcs, hooks, recaps, and payoffs.

It exists to:
- keep pacing consistent for the intended release cadence
- define hook/recap/payoff expectations
- prevent “outline drift” that ignores the serialized reading experience

## Module contract (Owns / Requires / Provides)

**Owns**
- Serialization engineering constraints: chapter length targets, cadence, hook/recap discipline, payoff rhythm, volume/arc pacing principles.

**Does not own**
- The outline/fine-outline content itself → `outline/`
- Prose voice rules → `spec/style/` (serialization only constrains structure/rhythm)

**Requires (upstream)**
- Preferably `spec/premise/` so cadence/hook/payoff match genre promise.
- If voice is tightly constrained: `spec/style/` to keep recap/hook style consistent.

**Provides (downstream)**
- Structural constraints that shape outline/fine-outline and reduce serialized “drop-off”.

## Definition of done (minimum viable)

At minimum, `spec/serialization/` should define one profile that includes:
- Target chapter length range and cadence expectations
- Hook policy (how often/what kind) and recap policy (if any)
- Payoff cadence expectations (resolve questions within N chapters / per arc)

## What belongs here (and what doesn’t)

Belongs in `spec/serialization/`:
- chapter length targets (ranges), cadence expectations, and constraints
- hook policy (how often, how strong, what style)
- recap policy (when allowed, how light)
- payoff cadence (how frequently to resolve questions/promises)
- volume/arc rhythm principles (high-level)

Does **not** belong in `spec/serialization/`:
- the actual outline/fine-outline content → `outline/`
- prose style rules → `spec/style/`
- ad-hoc chapter-by-chapter planning

## Outputs

- Spec entry files under `spec/serialization/`, each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/serialization-profile.md` as the default structure.

## How to write serialization entries

- Write constraints that can be checked (“chapter ends with a forward hook”, “payoff within N chapters”).
- Keep it minimal and stable; adapt only when the release model changes.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline is built, it should obey serialization constraints; anchor `@spec:<id>` when a structural decision depends on a serialization rule. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Serialization Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Are rules checkable without turning into an outline?
- Do constraints match the intended reading cadence?
- Is recap/hook/payoff discipline explicit enough to guide structure?
