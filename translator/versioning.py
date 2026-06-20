from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def versions_path_for(output_dir: Path) -> Path:
    """Find versions.json at <output_dir>/../versions/versions.json."""
    return output_dir.parent / "versions" / "versions.json"


def bump_version(
    output_dir: Path,
    game_version: str,
    lang_code: str,
) -> str:
    """Increment patch version for given channel+language, return new version."""
    path = versions_path_for(output_dir)

    if path.exists():
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}

    channel: dict[str, Any] = data.setdefault(game_version, {"languages": {}})
    languages: dict[str, Any] = channel.setdefault("languages", {})
    current = languages.get(lang_code, {}).get("version", "1.0.0")
    new_version = _bump_patch(current)
    languages[lang_code] = {"version": new_version}

    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(content, encoding="utf-8")

    return new_version


def _bump_patch(version: str) -> str:
    parts = version.split(".")

    if len(parts) != 3:  # noqa: PLR2004
        return "1.0.1"

    major, minor, patch = parts

    return f"{major}.{minor}.{int(patch) + 1}"
