---
name: spec-system
description: Define and maintain mechanism rules and boundaries under spec/system/ (magic/tech/power systems, triggers, costs, limits, failure modes, counters). Use when establishing the story’s “fair tools”, or when plot solutions feel like author fiat / sudden power-ups.
---

# spec-system

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- The story uses a mechanism/system (magic/tech/power/protocol/institution-as-system) that needs fairness boundaries.
- Plot solutions feel like author fiat / sudden power-ups (临时开挂/硬解).
- You need explicit costs/limits/failure/counters to constrain outline decisions.

## Quick start

1) Read existing `spec/system/` entries and summarize confirmed mechanics + boundaries.
2) If anything is missing/ambiguous, ask only the minimum questions (see `references/QUESTIONS.md`).
3) Draft in-chat, confirm with the user, then create/update entries via the spec workflow:
   - use `spec__propose` (one entry per id) and follow the template `assets/templates/system-rule.md` (structure only; do not copy its sample YAML into `body`)
   - apply only after explicit approval via `spec__apply`
4) Keep rules **checkable**: trigger → cost → limits → failure → counters.

## Tooling (Novelaire)

- Use `spec__query` / `spec__get` to find and read existing entries before creating new ids.
- Use `spec__propose` to generate a reviewable diff; apply with `spec__apply` only after approval.
- Do not write canon artifacts into this skill directory; `assets/` is for templates only.

## Purpose

`spec/system/` is the **fairness layer**: it defines what characters can do, what they cannot do, and what it costs.

It exists to:
- prevent “author solves it by inventing a new button” (临时开挂/硬解)
- make tension credible via limits, trade-offs, and failure modes
- keep escalation honest: new capability must be paid for (training, resources, risk, sacrifice, exposure, etc.)

## Module contract (Owns / Requires / Provides)

**Owns**
- Canon rules for mechanisms that solve problems (magic/tech/power/protocol): trigger/procedure, costs, hard/soft limits, failure modes, and (optional) counterplay.
- Anti-loophole constraints: what the system cannot do, what it cannot bypass, and what always has consequences.

**Does not own**
- World baselines and institutions → `spec/world/` (system rules can imply consequences; world records them).
- Character-specific capabilities → `spec/characters/` (characters reference system rules; they do not redefine them).
- Object-specific constraints → `spec/objects/` (objects may interface with the system; don’t duplicate mechanics here).

**Requires (upstream)**
- Preferably `spec/premise/` so “fairness” matches the reader promise.
- Preferably `spec/world/` so you can state plausible consequences (monitoring, scarcity, enforcement).
- If `spec/narrative/` constrains reveal discipline (mystery/suspense), system entries must not force early spoilers.

**Provides (downstream)**
- A stable rulebook used by outline/fine-outline/chapters to judge “allowed vs cheating solutions”.
- Constraints that downstream modules must obey: character abilities, object interfaces, and module fairness rules.

**Conflict resolution**
- If a scene “needs” a new capability, treat it as FAIL unless you first add a system rule (with cost/limit/failure) and get explicit user approval.

## Definition of done (minimum viable)

At minimum, `spec/system/` should include:
- One entry per *problem-solving* mechanism the story relies on (not every lore detail).
- For each mechanism: trigger/procedure, costs/trade-offs, limits/caps, failure modes.
- A clear “cannot / must not / cannot bypass” boundary list for anti-cheat.
- If the system risks overpowering: at least one counterplay/vulnerability pattern (no infinite negation).

## What belongs here (and what doesn’t)

Belongs in `spec/system/`:
- mechanisms (magic/tech/power/protocol/institution-as-system) that enable solutions across many scenes
- triggers/procedures, costs/trade-offs, limits/caps, failure modes
- counters/vulnerabilities boundaries (when they exist)

Does **not** belong in `spec/system/`:
- world baseline facts and institutions → `spec/world/`
- specific characters’ personal truths/resources → `spec/characters/`
- plot beats / “how chapter X resolves” → outline/fine-outline

## Outputs

- Spec entry files under `spec/system/` (one rule/object per file), each beginning with YAML frontmatter containing a stable `id`.
- Use `assets/templates/system-rule.md` as the default structure.

## How to write system entries

- Prefer explicit constraints (“If X then Y; cannot exceed Z; costs C”) over vibe language.
- Make “failure” and “counterplay” explicit enough to generate tension without cheating.
- Use the spec workflow tools (`spec__propose` / `spec__apply`) instead of editing spec files directly.

## Downstream use (anchors)

When outline/fine-outline depends on a system mechanic (a trick, a limit, a cost, a counter), add an anchor `@spec:<id>` pointing back to the relevant system entry. Anchors are **constraints**, not provenance.

## References

- Questions to ask (minimal): `references/QUESTIONS.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- System Gate checklist (PASS/WARN/FAIL oriented): `references/GATE.md`

## Self-check

- Can you say “this solution is allowed” or “this violates the system” from these entries alone?
- Are costs/limits/failure modes strong enough to prevent omnipotence?
- Did you accidentally encode plot beats or world baseline facts as “system rules”?
