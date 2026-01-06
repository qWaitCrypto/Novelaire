# System Gate (PASS/WARN/FAIL)

Use this to evaluate whether `spec/system/` is strong enough to keep solutions fair and tension honest.

## PASS

- System rules are **checkable**: trigger/procedure, costs, limits, failure modes are present.
- New capability is paid for (setup/training/resources/risk), not invented on demand.
- Counterplay exists *and is bounded* (no infinite negation).
- Entries do not encode plot beats; they define reusable mechanics.

## WARN

- Some rules are checkable but key pieces are missing (common: costs, failure, or limits).
- Counters exist but boundaries are unclear.
- Entries are too large or bundle unrelated mechanics (hard to reuse).

## FAIL

- Rules are “vibes”: cannot judge what is allowed.
- System is effectively omnipotent (no meaningful cost/cap/failure).
- Major contradictions with `spec/premise/` promise or `spec/world/` reality.
- The only way to resolve scenes is by introducing new rules mid-story.
