---
name: gate-consistency
description: Run the Consistency Gate (PASS/WARN/FAIL) to catch cross-chapter contradictions (character traits/state, world/system rules, timeline, who-knows-what) and produce a prioritized fix list.
---

# gate-consistency

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- You are about to draft the next chapter and the story state feels “fuzzy”.
- A chapter revision might introduce contradictions (character state, timeline, rules).
- The user explicitly asks to check “一致性/设定穿帮/前后矛盾/知情边界”.

## Quick start

1) Choose scope (one chapter, an arc, or a milestone span under `chapters/`).
2) Read relevant constraints (usually `spec/continuity/`, plus `spec/characters/`, `spec/world/`, `spec/system/`, `spec/timeline/` as needed).
3) Scan the text for contradictions and drift:
   - character traits / injuries / possessions / permissions
   - world + system rule compliance (limits, costs, exceptions)
   - timeline order + time passage plausibility
   - knowledge boundaries (“who knows what when”), consistent with POV
4) Output a Gate Report.

## Gate Report format

- **Target**: Consistency
- **Result**: PASS / WARN / FAIL
- **Findings**: list of `{severity, location, problem, suggested_fix}`
- **Next step**: continue / revise upstream / prioritize fixes / rollback

## References

- Detailed checklist + examples: `references/CONSISTENCY_CHECKS.md`

## Fix routing (where to repair)

- If the issue is caused by missing/weak canon, fix upstream first:
  - characters/state → `spec-characters` / `spec-continuity`
  - rules/boundaries → `spec-system` / `spec-world`
  - ordering/deadlines → `spec-timeline`
- If the canon is correct but prose drifted, revise the relevant chapter(s).
- If the inconsistency is intentional (lie / unreliable narrator), encode the intent as a constraint in the right spec domain so it stops flagging as “accidental drift”.

## Constraints

- Do not modify story files while running this gate; only report findings.
- Findings MUST be anchored to concrete text (file + line or quote).

## Self-check

- Are findings anchored to concrete text (quote/line) instead of vibe?
- Are suggested fixes upstream-first (outline/spec) when appropriate?
