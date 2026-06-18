from __future__ import annotations

from translator.models import RawLine


def make_batches(entries: list[RawLine], batch_size: int) -> list[list[RawLine]]:
    """Split translatable entries into chunks of at most batch_size."""
    return [entries[i : i + batch_size] for i in range(0, len(entries), batch_size)]
