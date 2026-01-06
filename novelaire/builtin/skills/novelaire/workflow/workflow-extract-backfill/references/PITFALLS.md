# Extraction/backfill pitfalls (and fixes)

## 1) Smuggling hypotheses into canon
- Symptom: spec contains unconfirmed guesses.
- Fix: only propose confirmed items; keep the rest in drafts as questions/options.

## 2) Wrong domain placement
- Symptom: system rules in world; character truths in factions; etc.
- Fix: route by responsibility; split entries when mixed.

## 3) One giant spec entry
- Symptom: everything gets bundled into one file.
- Fix: one object/rule per entry id; keep reusable granularity.

## 4) No review step
- Symptom: spec gets edited directly with no diff/approval.
- Fix: use `spec__propose` and show diffs; apply only after approval.
