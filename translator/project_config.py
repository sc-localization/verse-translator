from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-reattr]

_CONFIG_FILE = "verse-translator.toml"


def load() -> dict[str, Any]:
    """Load verse-translator.toml from the current working directory, if it exists."""
    path = Path(_CONFIG_FILE)
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def get_output_dir(config: dict[str, Any]) -> Path | None:
    try:
        return Path(config["output"]["dir"])
    except KeyError:
        return None


def get_defaults(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("defaults", {})
