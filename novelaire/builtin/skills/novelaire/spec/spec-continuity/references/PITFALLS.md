# Continuity pitfalls (and fixes)

## 1) State reset
- Symptom: injuries, debts, permissions vanish between chapters.
- Fix: track variables + transitions; require explicit explanation for resets.

## 2) Knowledge drift
- Symptom: people act on information they shouldn’t have.
- Fix: track knowledge states; align with `spec/narrative/` boundaries.

## 3) Ownership teleport
- Symptom: items appear/disappear without transfer.
- Fix: track ownership; link to `spec/objects/`.

## 4) Mixing timeline and continuity
- Symptom: timeline anchors are stored as variable lists (or vice versa).
- Fix: keep anchors in `spec/timeline/`; keep trackers in `spec/continuity/`.

## 5) Too many tracked variables
- Symptom: tracking becomes impossible.
- Fix: track only variables that repeatedly matter; keep it lean.
