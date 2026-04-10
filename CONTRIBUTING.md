# Contributing to Novelaire

Thanks for your interest. This is a solo project in active development, but bug reports and focused PRs are welcome.

## Setup

```bash
git clone https://github.com/qWaitCrypto/Novelaire.git
cd Novelaire
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v
```

All 137 tests run offline — no API keys needed.

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(tools): add web__search tool
fix(llm): handle empty stream chunk from OpenAI
refactor(runtime): split orchestrator into focused modules
```

- One subject line, no bullet points in the body unless genuinely needed
- Reference an issue if one exists: `fix(chat): crash on empty session (#12)`

## Branch naming

```
feat/short-description
fix/short-description
refactor/short-description
```

## What to work on

Check [open issues](https://github.com/qWaitCrypto/Novelaire/issues) first. If you want to propose something new, open an issue before starting a PR.

## Code style

- Python 3.12+, type-annotated
- Line length 100 (configured in `pyproject.toml`)
- No docstrings on internal helpers — self-evident names are preferred
