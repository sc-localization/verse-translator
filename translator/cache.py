from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO, TypedDict


class CacheEntry(TypedDict):
    src: str
    dst: str


Cache = dict[str, CacheEntry]  # key -> {src, dst}


def load(path: Path) -> Cache:
    if path.exists():
        cache: Cache = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                cache[record["key"]] = {"src": record["src"], "dst": record["dst"]}
        return cache

    return _load_legacy(path.with_suffix(".json"))


def _load_legacy(path: Path) -> Cache:
    """Read the pre-JSONL cache format (one JSON object keyed by entry key)."""
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))

    return {key: {"src": v["src"], "dst": v["dst"]} for key, v in data.items()}


def save(path: Path, cache: Cache) -> None:
    """Rewrite the whole cache — compacts duplicate keys left by append()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _write_records(f, cache)


def append(path: Path, records: Cache) -> None:
    """Append records without rewriting; on load, later lines win per key."""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        _write_records(f, records)


def _write_records(f: TextIO, records: Cache) -> None:
    for key, entry in records.items():
        line = json.dumps(
            {"key": key, "src": entry["src"], "dst": entry["dst"]},
            ensure_ascii=False,
        )
        f.write(line + "\n")


def cache_path_for(output_path: Path) -> Path:
    return output_path.parent / ".translation_cache.jsonl"
