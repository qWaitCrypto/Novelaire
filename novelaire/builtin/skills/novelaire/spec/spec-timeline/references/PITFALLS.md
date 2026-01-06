# Timeline pitfalls (and fixes)

## 1) Soft chronology that drifts
- Symptom: events slide around to fit scene convenience.
- Fix: promote only hard anchors into `spec/`; keep flexible sequencing in outline.

## 2) Missing deadlines (no pressure)
- Symptom: characters can “wait forever” and nothing forces action.
- Fix: define clocks and what changes at expiry.

## 3) Impossible travel/communication
- Symptom: characters appear where needed instantly.
- Fix: encode travel/latency constraints or adjust geography/tech in `spec/world/` / `spec/system/`.

## 4) Knowledge leaks
- Symptom: someone acts on info they shouldn’t have.
- Fix: track knowledge sequence (timeline entry or `spec/continuity/`).

## 5) Plot beats disguised as anchors
- Symptom: timeline entry is just a chapter list.
- Fix: rewrite as order constraints and irreversible state transitions.
