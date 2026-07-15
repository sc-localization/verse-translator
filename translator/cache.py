from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TextIO, TypedDict

logger = logging.getLogger(__name__)


class CacheEntry(TypedDict):
    src: str
    dst: str


Cache = dict[str, CacheEntry]  # key -> {src, dst}


def load(path: Path) -> Cache:
    if path.exists():
        cache: Cache = {}
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    cache[record["key"]] = {"src": record["src"], "dst": record["dst"]}
                except (json.JSONDecodeError, KeyError) as exc:
                    # A hard kill mid-append can leave a truncated last line —
                    # this is the crash-recovery file, so it must never itself
                    # block recovery. Drop the bad line and keep going.
                    logger.warning(
                        "Skipping corrupt cache line %d in %s: %s", lineno, path, exc
                    )
        return cache

    legacy = _load_legacy(path.with_suffix(".json"))
    if legacy:
        # Migrate immediately so an interrupted run doesn't leave a jsonl
        # cache that shadows the legacy file and hides its translations.
        save(path, legacy)
    return legacy


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
