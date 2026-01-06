# Object pitfalls (and fixes)

## 1) “Magic prop” creep
- Symptom: capabilities expand when needed.
- Fix: define explicit limits, failure modes, and “cannot”.

## 2) Ownership teleport
- Symptom: items appear/disappear without consequence.
- Fix: define ownership and transfer rules; track in `spec/continuity/` if needed.

## 3) Missing scarcity/cost
- Symptom: resources are limitless, reducing tension.
- Fix: encode depletion, access constraints, and replacement difficulty.

## 4) Mixing system mechanics
- Symptom: the object entry contains the whole power system.
- Fix: move mechanics to `spec/system/`; keep object as interface.

## 5) Plot beats disguised as canon
- Symptom: “in chapter 6 it breaks” inside spec.
- Fix: move beats to outline; keep stable rules here.
