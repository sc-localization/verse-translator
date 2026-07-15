from __future__ import annotations

from translator.models import RawLine

# Conservative source-chars budget when the backend does not report a context length
DEFAULT_MAX_CHARS = 6000


def make_batches(
    entries: list[RawLine], batch_size: int, max_chars: int = DEFAULT_MAX_CHARS
) -> list[list[RawLine]]:
    """Split entries into batches of at most batch_size entries and ~max_chars
    total source characters.

    A single entry longer than max_chars gets its own batch; the pipeline
    splits it into text chunks before sending it to the model.
    """
    batches: list[list[RawLine]] = []
    current: list[RawLine] = []
    current_chars = 0

    for entry in entries:
        length = len(entry.value or "")
        too_full = len(current) >= batch_size or current_chars + length > max_chars
        if current and too_full:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += length

    if current:
        batches.append(current)

    return batches
