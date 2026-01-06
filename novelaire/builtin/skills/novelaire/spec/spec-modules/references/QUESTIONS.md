# Modules questions (ask only what’s missing)

Use these when enabling a module under `spec/modules/<name>/`.

## Minimum set (usually enough)

1) **Do we actually need the module?**
- What mechanism is present that requires special constraints?

2) **What is the fairness contract?**
- What must be true for readers to feel the mechanism is fair (mystery clues, romance progression, progression costs)?

3) **What is explicitly forbidden?**
- List 3–7 cheats/patterns that break trust.

4) **What must be tracked?**
- Any module-specific state variables or checklists?
