---
name: tech-dialogue
description: Improve dialogue to feel natural and character-specific (subtext, voice, tension, beats). Use when drafting/revising dialogue-heavy scenes or when dialogue sounds generic/AI-like.
---

# tech-dialogue

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- Dialogue feels generic/AI-like (same cadence for every speaker, over-explains, no subtext).
- The scene is dialogue-heavy but has low tension or no directional pressure.
- A character’s voice is drifting (OOC risk).

## Quick start (runbook)

1) Diagnose (2 minutes): name the failure mode(s) + cite 1–2 concrete lines as evidence.
2) Lock voice (if needed): fill a voice sheet from `assets/templates/voice-sheet.md` (or update existing character voice in `spec/characters/*`).
3) Build pressure: write a dialogue intent map using `assets/templates/dialogue-intents.md`.
4) Apply “surgical” edits: change only the dialogue lines and nearby beats that carry the problem.
5) Self-check with `references/CHECKLIST.md`, then optionally suggest a gate for verification.

## Inputs (what to read)

- The target dialogue passage (chapter/scene).
- Relevant canon constraints when available:
  - character boundaries/voice: `spec/characters/*`
  - style contract: `spec/style/*`
  - narrative/POV rules (no cheating exposition): `spec/narrative/*`

## Purpose

This skill helps produce dialogue that is:
- character-specific (voice differences are audible)
- tense (conflict/pressure exists even in “polite” scenes)
- economical (no info-dump “as you know” speech)

## Diagnose (common failure modes)

- **Same-voice drift**: everyone has similar sentence length, vocabulary, politeness level.
- **Info dump**: characters say things only the reader needs, not what they would say.
- **Zero pressure**: lines don’t negotiate anything; no leverage, no refusal, no consequence.
- **No embodiment**: endless back-and-forth with no beats, no space, no physicality.
- **Too explicit**: motives and feelings are stated instead of implied via subtext.

## Surgical edit menu (prefer these over rewriting)

Pick a few actions and apply locally:
- Replace explanation lines with **subtext questions** or **deflections**.
- Add one **refusal** (“I won’t talk about that”) to create a boundary.
- Add one **leverage beat** (object, timer, third party listening, physical constraint).
- Introduce a **micro-turn** (new info, misunderstanding, concession, threat, promise).
- Move necessary exposition out of dialogue into **action/setting/afterthought**.
- Vary turns: interruption, silence, overlap, unfinished sentence, changed subject.

## Output expectations

- The revised dialogue passage (minimal, targeted edits).
- Optional artifacts (only if useful):
  - A voice sheet: `assets/templates/voice-sheet.md`
  - A dialogue intent map: `assets/templates/dialogue-intents.md`

## Output

- Revised dialogue text in the relevant draft/chapter.
- Optional: a short “dialogue intent map” using `assets/templates/dialogue-intents.md`.

## Applying changes (editing discipline)

- Prefer localized edits (change the dialogue lines and nearby beats) instead of rewriting entire chapters.
- When modifying project files, use `project__apply_edits` so the user can review small, controlled diffs.

## References

- Revision checklist: `references/CHECKLIST.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Deep techniques (ported reference): `references/TECHNIQUES.md`

## Self-check

- Can you identify who is speaking without tags?
- Is there subtext (stakes) instead of pure information transfer?
- Do lines create pressure or change something (not just filler)?

## Optional: verification gate

If this change is important (voice continuity risk, canon constraints, or large edits), suggest running a verifier gate:
- `gates/gate-chapter` (for prose quality + continuity)
- `gates/gate-consistency` (for cross-file voice/canon consistency)
