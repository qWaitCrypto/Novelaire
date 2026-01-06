# Continuity Gate (PASS/WARN/FAIL)

Use this to evaluate whether `spec/continuity/` prevents contradictions and state reset.

## PASS

- Tracked state variables are explicit and limited to what matters.
- Knowledge boundaries are trackable and align with `spec/narrative/`.
- Ownership/access transitions are consistent with `spec/objects/`.
- Invariants are clear and checkable.

## WARN

- Variables exist but transitions are unclear.
- Knowledge tracking is partial.
- The tracker is bloating with low-value variables.

## FAIL

- Recurring contradictions persist.
- State resets happen without explanation.
- Who-knows-what is inconsistent across chapters.
