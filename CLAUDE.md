# CLAUDE.md

## Project Overview

**verse-translator** — pipeline for translating Star Citizen `global.ini` using local LLMs (LM Studio / Ollama). Outputs ready-to-deploy translation files for **lingvo-injector** server.

## Commands

```bash
uv sync                          # Install dependencies
uv run python -m translator      # Run translation pipeline
uv run pytest tests/             # Run tests
```

## Architecture

```
global.ini (EN)
  → parser: split into batches
  → LM Studio / Ollama: translate each batch with SC glossary
  → assembler: merge back into global.ini (RU)
  → output: server/translations/{VERSION}/ru/global.ini
```

## Key Design Decisions

- Default backend: LM Studio with `qwen2.5-coder-14b-instruct`; Ollama as alternative
- Preserves INI format: `key=value`, comments (`; ...`), empty lines
- Game variables (`~mission()`, `@ui_`, `%ls`, etc.) must NOT be translated
- SC glossary injected into every batch prompt
- Output path mirrors lingvo-injector's `server/translations/` structure

## Linked Projects

- **lingvo-injector**: `../lingvo-injector` — consumes output of this pipeline
- **VerseBridge**: `../VerseBridge` — archived ML predecessor

## Code Conventions

- Python 3.10, uv package manager
- Type hints everywhere, strict mypy
- Conventional Commits
- After changes: propose commit message, do NOT execute
