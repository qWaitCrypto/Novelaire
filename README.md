# Novelaire

[![CI](https://github.com/qWaitCrypto/Novelaire/actions/workflows/ci.yml/badge.svg)](https://github.com/qWaitCrypto/Novelaire/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Spec-driven vibe writing CLI.** Treat your story like code — define the soul, lint the vibe.

> "Don't just prompt it. Spec it."

---

## What is Novelaire?

Novelaire is a CLI writing agent that applies software engineering discipline to creative writing. Instead of one-shot prompting, you build a structured **Spec layer** (world, characters, continuity rules) that every generated chapter must satisfy. The LLM writes prose; the Specs and Gates hold it accountable.

Think of it as **TDD for fiction**:
- Specs are your canonical source of truth
- Gates are your test suite (PASS / WARN / FAIL)
- Sessions are your version history
- Snapshots let you roll back bad chapters

---

## Architecture

```
┌─────────────┐
│  novelaire  │  CLI entry point (init / chat / session)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│                    Orchestrator                     │
│  event bus · approval flow · context compaction    │
└───────────┬────────────────────────┬────────────────┘
            │                        │
            ▼                        ▼
  ┌──────────────────┐    ┌──────────────────────────┐
  │   LLM Router     │    │         Tools             │
  │ Anthropic / OpenAI│   │ project__read/write/glob  │
  │ / Gemini          │   │ project__apply_edits      │
  └──────────────────┘    │ project__aigc_detect      │
                          │ web__fetch / web__search  │
                          │ spec_workflow · snapshot  │
                          │ subagent__run (delegated) │
                          └──────────────────────────┘
            │
            ▼
  ┌──────────────────────────────┐
  │       Skills (built-in)      │
  │  spec-*   (15 spec modules)  │
  │  workflow-* (outline/brainstorm) │
  │  gate-*   (7 verification gates) │
  └──────────────────────────────┘
            │
            ▼
  ┌──────────────────────────────┐
  │     Project on disk          │
  │  .novelaire/ · spec/ · outline/ │
  │  fine-outline/ · chapters/   │
  └──────────────────────────────┘
```

---

## Quick Start

### Install

```bash
git clone https://github.com/qWaitCrypto/Novelaire.git
cd Novelaire
pip install -e .
```

### Configure LLM

Create `~/.novelaire/config/models.json` (or `./.novelaire/config/models.json` per project):

```json
{
  "profiles": {
    "default": {
      "model": "claude-sonnet-4-5",
      "provider": "anthropic",
      "credential_ref": { "kind": "env", "env": "ANTHROPIC_API_KEY" }
    }
  }
}
```

Set the API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Start writing

```bash
# Initialize a new novel project
novelaire init my-novel/

cd my-novel/

# Open a writing session
novelaire chat
```

Inside the chat, use built-in skills:

```
/spec-premise       — define your story's central premise
/spec-characters    — establish characters and their arcs
/workflow-outline   — generate a chapter-level outline
/gate-spec          — verify all specs are internally consistent
/workflow-fine-outline  — expand into scene-level beats
/gate-fine-outline  — gate check before writing
```

### Resume a session

```bash
novelaire session list
novelaire session resume
```

---

## Skills Reference

Novelaire ships with 22 built-in skills organized into three groups:

| Group | Skills | Purpose |
|-------|--------|---------|
| `spec-*` | premise, narrative, style, characters, world, locations, factions, objects, timeline, glossary, continuity, quality, serialization, modules, system | Build and maintain the Spec layer |
| `workflow-*` | outline, fine-outline, brainstorm-capture, extract-backfill | Drive the writing workflow |
| `gate-*` | spec, outline, fine-outline, chapter, consistency, regression, forgotten-elements | Verify quality before moving forward |

---

## Multi-provider LLM

Novelaire routes to any OpenAI-compatible endpoint, Anthropic, or Gemini. Configure multiple profiles and switch per-session:

```json
{
  "profiles": {
    "fast":  { "model": "gpt-4o-mini", "provider": "openai", ... },
    "heavy": { "model": "claude-opus-4-5", "provider": "anthropic", ... }
  }
}
```

---

## AIGC Detection

The `project__aigc_detect` tool runs an **offline** classifier against your chapters to flag AI-generated passages before submission. No network call — the model runs locally via HuggingFace Transformers.

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

137 unit tests, no network calls required.

---

## License

MIT © 2025 qWaitCrypto
