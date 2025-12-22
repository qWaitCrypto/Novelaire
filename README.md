# Novelaire 🖋️

**Spec-Driven Vibe Writing CLI.**
Treat your story like code. Define the soul, lint the vibe.

> "Don't just prompt it. Spec it."

---

### 📖 What is Novelaire?

Novelaire is a command-line interface that brings **Software Engineering principles** to creative writing. It moves beyond fragile prompt engineering by using **explicit Specifications (Specs)** to control the generation, consistency, and tone of your story.

It turns the writing process into a **TDD (Text-Driven Development)** workflow.

---

### ⚙️ Runtime LLM config (WIP)

- Project models: `./.novelaire/config/models.json`
- Global models: `~/.novelaire/config/models.json`
- Override config paths:
  - `NOVELAIRE_PROJECT_MODELS_PATH` (absolute or relative to project root)
  - `NOVELAIRE_GLOBAL_MODELS_PATH`
- Secrets stay in environment variables (referenced by `credential_ref.kind=env`)
