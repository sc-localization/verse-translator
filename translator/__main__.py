from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from translator.backends.lmstudio import LMStudioBackend
from translator.config import Config
from translator.pipeline import run
from translator.project_config import get_defaults, get_output_dir
from translator.project_config import load as load_config


class TqdmLoggingHandler(logging.Handler):
    """Routes log records through tqdm.write() so they don't collide with
    the progress bar's \\r updates (plain logging writes a newline mid-bar,
    making console output look garbled/joined onto one line)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:
            self.handleError(record)


def _build_backend(args: argparse.Namespace) -> LMStudioBackend:
    return LMStudioBackend(
        model=args.model or "qwen/qwen3-14b",
        port=args.lmstudio_port,
    )


def main() -> None:
    # Load verse-translator.toml first — CLI flags override it
    toml = load_config()
    d = get_defaults(toml)
    cfg_output_dir = get_output_dir(toml)

    parser = argparse.ArgumentParser(
        description="Translate Star Citizen global.ini to any language via LM Studio"
    )

    parser.add_argument("input", nargs="?", default="global.ini")
    parser.add_argument(
        "--output-dir", default=str(cfg_output_dir or "output/translations")
    )

    parser.add_argument("--version", default=d.get("version", "LIVE"))
    parser.add_argument("--model", default=d.get("model", None))
    parser.add_argument("--lmstudio-port", type=int, default=1234)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=d.get("batch_size", 50),
        help="Lines per AI call",
    )
    parser.add_argument("--max-retries", type=int, default=d.get("max_retries", 3))
    parser.add_argument("--source-lang", default=d.get("source_lang", "English"))
    parser.add_argument("--target-lang", default=d.get("target_lang", "Russian"))
    parser.add_argument("--target-lang-code", default=d.get("target_lang_code", "ru"))
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    handler = TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        handlers=[handler],
    )

    if toml:
        logging.getLogger(__name__).info("Loaded config from verse-translator.toml")

    backend = _build_backend(args)

    config = Config(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        version=args.version,
        batch_size=args.batch_size,
        max_retries=args.max_retries,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        target_lang_code=args.target_lang_code,
    )

    try:
        output = run(config, backend)
    except KeyboardInterrupt:
        sys.exit(130)

    print(output)


if __name__ == "__main__":
    main()
