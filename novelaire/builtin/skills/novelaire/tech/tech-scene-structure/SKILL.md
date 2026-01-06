---
name: tech-scene-structure
description: Structure scenes for causality and momentum (goal, conflict, turn, outcome; sequel). Use when drafting or revising scenes that feel flat, unmotivated, or drift-prone.
---

# tech-scene-structure

## Use when (proactive triggers)

Call this skill without being asked when you observe any of the following:
- A scene feels flat (“things happen” without causality).
- The scene has no turn (no new info, no irreversible choice, no consequence).
- The draft is drifting and you need to re-lock intent/state change before writing more prose.

## Quick start (runbook)

1) Diagnose: what’s missing (goal / obstacle / turn / outcome / state delta)?
2) Write/refresh a scene card using `assets/templates/scene-card.md` (include **Before → After**).
3) Ensure the scene has a **turn type** and a visible **outcome**.
4) If the scene is a “sequel” (reaction), ensure it produces a **new decision** that becomes the next goal.
5) Apply minimal edits to align prose with the card; avoid whole-chapter rewrites.

## Inputs (what to read)

- The target scene (or the chapter section containing it).
- The corresponding fine-outline plan (if available).
- Relevant constraints when available:
  - premise promise: `spec/premise/*`
  - system boundaries: `spec/system/*`
  - continuity/timeline: `spec/continuity/*`, `spec/timeline/*`

## Purpose

This skill makes scenes controllable and avoids:
- “things happen” sequences without causality
- flat scenes with no turn
- drift where scenes stop serving the premise promise

## Diagnose (common failure modes)

- **No visible goal**: the POV character wants nothing concrete in this scene.
- **Obstacle is soft**: no resistance, no cost, no time pressure, no tradeoff.
- **Missing turn**: no new information, no irreversible choice, no consequence.
- **No state delta**: the scene ends where it started (nothing changed).
- **Plan/prose mismatch**: fine-outline intent says one thing; prose does another.

## Surgical edit menu (prefer these over rewriting)

- Start later: enter as close to conflict as possible.
- Introduce a constraint: deadline, limited resource, third-party presence, system boundary.
- Create a turn: reveal, cost, decision, consequence; make it explicit in action.
- Force a choice: remove “easy outs” so the character must commit.
- End with a changed state: new plan, new leverage, new loss, new promise.

## Output

- A scene card (optional) + revised scene plan/prose.

## Applying changes (editing discipline)

- Prefer fixing the plan first (fine-outline), then aligning prose to the plan.
- When modifying project files, use `project__apply_edits` so the user can review small, controlled diffs.

## References

- Scene checklist: `references/CHECKLIST.md`
- Common pitfalls + fixes: `references/PITFALLS.md`
- Deep techniques (ported reference): `references/TECHNIQUES.md`

## Self-check

- Does the scene start with a goal and end with a changed state?
- Is there a clear obstacle and consequence?
- Does the turn push the mainline forward (not sideways)?

## Optional: verification gate

If the scene interacts with canon/system limits or has continuity risk, suggest a verifier gate:
- `gates/gate-fine-outline` (if you changed scene intent/plan)
- `gates/gate-chapter` (if you changed prose substantially)
