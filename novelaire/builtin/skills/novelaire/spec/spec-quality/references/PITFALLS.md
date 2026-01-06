# Quality pitfalls (and fixes)

## 1) Vague criteria
- Symptom: “write better” rules that can’t be checked.
- Fix: rewrite as PASS/WARN/FAIL conditions.

## 2) Too many gates
- Symptom: process becomes heavy and blocks writing.
- Fix: keep only gates that prevent expensive rework.

## 3) Thresholds that are not stable
- Symptom: numbers change every week.
- Fix: only encode stable thresholds; keep flexible targets in workflow discussions.

## 4) Gates disconnected from reality
- Symptom: gates don’t map to real failure modes.
- Fix: revise based on actual regression pain points.
