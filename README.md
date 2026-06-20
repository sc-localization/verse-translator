<p align="center">
  <img src="https://github.com/sc-localization/.github/blob/main/assets/community.png?raw=true" width="100" alt="Made by the community">
</p>

<p align="center"><em>This is an unofficial Star Citizen fansite and fan localization tool. It is not affiliated with the Cloud Imperium group of companies. All content on this site not authored by its host or users are property of their respective owners.</em></p>

# verse-translator

Pipeline for translating Star Citizen `global.ini` localization files using AI CLI agents and local models. Automates what you'd otherwise do manually: split the file into batches, send each batch with a prompt to an AI tool, collect responses, and assemble the translated file.

Translated files are meant to be published to [sc-translations](https://github.com/sc-localization/sc-translations) and served to users via jsDelivr CDN.

## How it works

```
global.ini (EN)
  → parser       — split into key=value entries, skip comments and empty lines
  → filter       — skip untranslatable values (pure variables, empty strings)
  → cache lookup — skip already translated entries that haven't changed
  → batcher      — split remaining entries into chunks of N lines
  → backend      — send each batch as a JSON array to an AI tool, get JSON back
  → assembler    — merge translations back into global.ini preserving original structure
  → {output_dir}/{VERSION}/{lang}/global.ini
```

On subsequent runs only new or changed lines are sent to the model — everything else is taken from cache.

## Supported backends

| Backend    | Command used               | Auth                              |
| ---------- | -------------------------- | --------------------------------- |
| `claude`   | `claude --print "..."`     | Claude account / Pro subscription |
| `gemini`   | `agy -p "..."`             | Google account                    |
| `codex`    | `codex -q "..."`           | OpenAI account                    |
| `ollama`   | `ollama run <model> "..."` | None — runs locally               |
| `lmstudio` | HTTP `localhost:1234`      | None — runs locally               |

## Setup

```bash
# Install uv if needed
curl -Ls https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Copy and edit config
cp verse-translator.example.toml verse-translator.toml
```

Make sure the CLI tool you want to use is installed and available in `$PATH`:

- **claude**: [Claude Code](https://claude.ai/code)
- **gemini**: [agy CLI](https://antigravity.google/docs/cli-using)
- **codex**: `npm install -g @openai/codex`
- **ollama**: [ollama.com](https://ollama.com)
- **lmstudio**: [lmstudio.ai](https://lmstudio.ai) — start the local server in the UI before running

## Configuration

Settings are read from `verse-translator.toml` (gitignored — each contributor has their own).
Copy the example and adjust paths:

```bash
cp verse-translator.example.toml verse-translator.toml
```

```toml
[output]
dir = "../sc-translations/translations"  # path to your local clone of sc-translations

[defaults]
backend = "claude"
version = "LIVE"
target_lang = "Russian"
target_lang_code = "ru"
batch_size = 50
```

CLI flags always override the config file.

## Supported languages

| `--target-lang-code` | `--target-lang` | Language             |
| -------------------- | --------------- | -------------------- |
| `ru`                 | `Russian`       | Русский              |
| `zh`                 | `Chinese`       | Chinese (Simplified) |
| `fr`                 | `French`        | French               |
| `de`                 | `German`        | German               |
| `it`                 | `Italian`       | Italian              |
| `ja`                 | `Japanese`      | Japanese             |
| `ko`                 | `Korean`        | 한국어 (Korean)      |
| `pl`                 | `Polish`        | Polish               |
| `pt`                 | `Portuguese`    | Portuguese           |
| `es`                 | `Spanish`       | Spanish              |

Translations are published to [sc-translations](https://github.com/sc-localization/sc-translations) and served via jsDelivr CDN:

```
https://cdn.jsdelivr.net/gh/sc-localization/sc-translations@main/translations/{VERSION}/{LANG}/global.ini
```

## Usage

```bash
# Uses settings from verse-translator.toml
uv run python -m translator input/global.ini

# Override backend
uv run python -m translator input/global.ini --backend gemini

# Override output dir (e.g. for local testing)
uv run python -m translator input/global.ini --output-dir output/

# Ollama with a specific model
uv run python -m translator input/global.ini --backend ollama --model qwen2.5:7b

# LM Studio (server must be running on port 1234)
uv run python -m translator input/global.ini --backend lmstudio --model "my-loaded-model"

# Translate to German
uv run python -m translator input/global.ini --target-lang German --target-lang-code de

# PTU version
uv run python -m translator input/global.ini --version PTU
```

## Publishing translations

After translation, push the result to [sc-translations](https://github.com/sc-localization/sc-translations):

```bash
cd ../sc-translations
git add translations/LIVE/ru/global.ini versions/versions.json
git commit -m "chore: update LIVE ru translation"
git push
```

Or use the helper script:

```bash
./translate-and-publish.sh
```

## All options

```
positional:
  input                  Path to source global.ini (default: global.ini)

options:
  --backend              claude | gemini | codex | ollama | lmstudio  (default from toml or claude)
  --model                Model name; each backend has a sensible default
  --version              Game version tag for output path  (default from toml or LIVE)
  --output-dir           Base output directory  (default from toml or output/translations)
  --target-lang          Target language name, e.g. German, French  (default from toml or Russian)
  --target-lang-code     Language code for output path, e.g. de, fr  (default from toml or ru)
  --source-lang          Source language name  (default: English)
  --batch-size           Lines per AI call  (default from toml or 50)
  --max-retries          Retries per batch on failure  (default from toml or 3)
  --lmstudio-port        LM Studio server port  (default: 1234)
  -v, --verbose          Debug logging (shows prompts and responses)
```

## Variable preservation

The pipeline instructs the model to leave game variables untouched:

| Pattern   | Example         | Meaning             |
| --------- | --------------- | ------------------- |
| `~func()` | `~mission(foo)` | Game function call  |
| `@tag`    | `@ui_label`     | UI reference        |
| `%ls`     | `%ls`           | String placeholder  |
| `{0}`     | `{1}`           | Positional argument |
| `\n`      | `\n`            | Newline escape      |
| `<tag>`   | `<bold>`        | Markup tag          |

Entries whose values consist entirely of variables are skipped and copied as-is.

## Incremental translation

After each run a `.translation_cache.json` file is saved next to the output `global.ini`.
On the next run:

- unchanged lines → taken from cache, no AI call
- new or changed lines → translated and cache updated

Cache is per version and language, so LIVE/ru and PTU/ru have independent caches.

## Development

```bash
uv run pytest tests/       # run tests
uv run mypy translator/    # type check
```

## Linked projects

- **sc-translations** — stores translated files, served via jsDelivr CDN
- **lingvo-injector** — desktop app that downloads and installs translations into the game
