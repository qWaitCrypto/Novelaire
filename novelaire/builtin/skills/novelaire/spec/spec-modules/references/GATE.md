# Modules Gate (PASS/WARN/FAIL)

Use this to evaluate whether `spec/modules/` improves fairness without bloating spec.

## PASS

- Modules are opt-in and only created when needed.
- Fairness constraints are explicit and enforceable.
- Forbidden patterns are clear and map to real “cheat” risks.
- Entries link to global canon instead of duplicating it.

## WARN

- The module scope is unclear or too broad.
- Constraints exist but are vague.
- The module is growing long and hard to apply.

## FAIL

- Modules are created by default, bloating spec.
- Mechanism fairness is not constrained; cheating is still possible.
- Module entries duplicate global canon or become outlines.
