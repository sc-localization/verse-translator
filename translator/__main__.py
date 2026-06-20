from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from translator.backends.base import TranslatorBackend
from translator.backends.lmstudio import LMStudioBackend
from translator.backends.ollama import OllamaBackend
from translator.config import Config
from translator.pipeline import run
from translator.project_config import get_defaults, get_output_dir
from translator.project_config import load as load_config

BACKENDS = ["ollama", "lmstudio"]


def _build_backend(args: argparse.Namespace) -> TranslatorBackend:
    if args.backend == "ollama":
        return OllamaBackend(model=args.model or "qwen2.5:14b")

    if args.backend == "lmstudio":
        return LMStudioBackend(
            model=args.model or "qwen2.5-coder-14b-instruct",
            port=args.lmstudio_port,
        )

    raise ValueError(f"Unknown backend: {args.backend}")


_AVG_TOKENS_PER_ENTRY = 25
_PROMPT_OVERHEAD_TOKENS = 500
_AUTO_BATCH_MIN = 10
_AUTO_BATCH_MAX = 200


def _auto_batch_size(backend: TranslatorBackend) -> int:
    ctx = backend.context_length()

    if ctx is None:
        logging.getLogger(__name__).warning(
            "Backend %s did not return context length, falling back to batch_size=50",
            backend.name,
        )

        return 50

    # Use half the context for input (other half reserved for output)
    input_budget = ctx // 2 - _PROMPT_OVERHEAD_TOKENS
    size = max(
        _AUTO_BATCH_MIN, min(_AUTO_BATCH_MAX, input_budget // _AVG_TOKENS_PER_ENTRY)
    )

    return size


def main() -> None:
    # Load verse-translator.toml first — CLI flags override it
    toml = load_config()
    d = get_defaults(toml)
    cfg_output_dir = get_output_dir(toml)

    parser = argparse.ArgumentParser(
        description="Translate Star Citizen global.ini to any language"
        " via CLI agents or local models"
    )

    parser.add_argument("input", nargs="?", default="global.ini")
    parser.add_argument(
        "--output-dir", default=str(cfg_output_dir or "output/translations")
    )

    parser.add_argument("--version", default=d.get("version", "LIVE"))
    parser.add_argument(
        "--backend", choices=BACKENDS, default=d.get("backend", "lmstudio")
    )

    parser.add_argument("--model", default=d.get("model", None))
    parser.add_argument("--lmstudio-port", type=int, default=1234)
    parser.add_argument(
        "--batch-size",
        default=str(d.get("batch_size", 50)),
        help="Lines per AI call, or 'auto' to detect from model context window",
    )
    parser.add_argument("--max-retries", type=int, default=d.get("max_retries", 3))
    parser.add_argument("--source-lang", default=d.get("source_lang", "English"))
    parser.add_argument("--target-lang", default=d.get("target_lang", "Russian"))
    parser.add_argument("--target-lang-code", default=d.get("target_lang_code", "ru"))
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if toml:
        logging.getLogger(__name__).info("Loaded config from verse-translator.toml")

    backend = _build_backend(args)

    if str(args.batch_size).lower() == "auto":
        batch_size = _auto_batch_size(backend)
        logging.getLogger(__name__).info("Auto batch size: %d", batch_size)
    else:
        batch_size = int(args.batch_size)

    config = Config(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        version=args.version,
        batch_size=batch_size,
        max_retries=args.max_retries,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        target_lang_code=args.target_lang_code,
    )

    output = run(config, backend)
    print(output)


if __name__ == "__main__":
    main()
