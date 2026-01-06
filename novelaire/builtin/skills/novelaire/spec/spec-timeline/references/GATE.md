# Timeline Gate (PASS/WARN/FAIL)

Use this to evaluate whether `spec/timeline/` prevents time drift and supports believable pressure.

## PASS

- Hard anchors exist and are checkable.
- Non-negotiable order/dependencies are explicit.
- Deadlines/clocks exist where pressure is needed.
- Irreversible state transitions are captured.
- Entries are stable canon, not chapter plans.

## WARN

- Anchors exist but order constraints are vague.
- Deadlines are implied but not operational.
- Knowledge sequence is under-specified, risking leaks.

## FAIL

- Chronology is flexible per scene convenience.
- No pressure clocks exist despite story needing urgency.
- Contradictions with `spec/world/` or `spec/system/` make timing impossible.
