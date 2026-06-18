from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class CacheEntry(TypedDict):
    src: str
    dst: str


Cache = dict[str, CacheEntry]  # key -> {src, dst}


def load(path: Path) -> Cache:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, cache: Cache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_path_for(output_path: Path) -> Path:
    return output_path.parent / ".translation_cache.json"
