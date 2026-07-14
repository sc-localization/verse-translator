from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from tqdm import tqdm

from translator.backends.base import ContextTooLongError, TranslatorBackend
from translator.backends.lmstudio import LMStudioBackend
from translator.batcher import make_batches
from translator.cache import (
    Cache,
    cache_path_for,
)
from translator.cache import (
    load as load_cache,
)
from translator.cache import (
    save as save_cache,
)
from translator.config import Config
from translator.models import LineKind, ParsedIni, RawLine
from translator.parser import assemble_entries, parse
from translator.versioning import bump_version

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional video game localization translator.
Translate the Star Citizen UI text from {source_lang} into {target_lang}.

Rules:
- Translate only human-readable text. Do NOT translate variables: ~func(), @tag, %ls, {{0}}, \\n, <tags>.
- Keep the sci-fi tone and atmosphere of the original.
- Preserve capitalisation style (ALL CAPS stays ALL CAPS, Title Case stays Title Case).
- Proper nouns (locations, ships, corporations, star systems, people) must NEVER be translated — keep them exactly as written in English.
- If the text looks like an organization, faction, service, or brand name — do NOT translate it. Keep it in English.
- When in doubt whether something is a proper noun — keep it in English.
- Company names and their legal suffixes (LLC, Inc., Corp., Ltd., Co.) must NEVER be translated or transliterated — keep the full name in English.
- Star system names include the word "System" — keep the full phrase in English (e.g. "Stanton System" stays "Stanton System", NOT "Система Стантон").
- Abbreviations (ALL CAPS words of 5 characters or fewer, e.g. HUD, VTOL, SHD, ESP, EMP, SCU, UEC, aUEC) must NEVER be translated — keep them as-is.
"""


def build_system_prompt(config: Config) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        source_lang=config.source_lang,
        target_lang=config.target_lang,
    )


def run(config: Config, backend: TranslatorBackend) -> Path:
    """Full pipeline: parse → cache lookup → batch → translate → assemble."""
    cache_path = cache_path_for(config.output_path)
    print(
        f"\n"
        f"  Input:    {config.input_path}\n"
        f"  Output:   {config.output_path}\n"
        f"  Cache:    {cache_path}\n"
        f"  Language: {config.source_lang} → {config.target_lang}\n"
        f"  Backend:  {backend.name}\n"
    )

    parsed: ParsedIni = parse(config.input_path)

    translatable = parsed.translatable_entries()
    cache = load_cache(cache_path)

    hits, misses = _split_by_cache(translatable, cache)

    total = len(translatable)
    cached = len(hits)
    remaining = len(misses)
    pct = cached * 100 // total if total else 0
    print(f"  Progress: {cached}/{total} translated ({pct}%), {remaining} remaining\n")

    # Apply cached translations and write them first
    for entry in hits:
        entry.translated = cache[entry.key or ""]["dst"]

    miss_keys = {e.key for e in misses}
    initial_entries = [
        line
        for line in parsed.lines
        if line.kind == LineKind.ENTRY and line.key not in miss_keys
    ]

    # Write cached + untranslatable entries; misses are appended after translation
    assemble_entries(initial_entries, config.output_path, append=False)

    if not misses:
        save_cache(cache_path, cache)
        logger.info("Cache saved to %s", cache_path)
        return config.output_path

    if isinstance(backend, LMStudioBackend):
        backend.ensure_model_loaded()

    system_prompt = build_system_prompt(config)

    # Identical source strings are translated once and fanned out to every key
    groups: dict[str, list[RawLine]] = {}
    for entry in misses:
        groups.setdefault(entry.value or "", []).append(entry)
    unique = [group[0] for group in groups.values()]
    if len(unique) < len(misses):
        print(f"  Dedup:    {len(misses)} entries → {len(unique)} unique strings\n")

    batches = make_batches(unique, config.batch_size)
    total_batches = len(batches)

    with tqdm(
        total=total,
        initial=cached,
        unit="entry",
        desc="Translating",
    ) as bar:
        for batch_idx, batch in enumerate(batches):
            values = [entry.value or "" for entry in batch]
            translated = _translate_with_retry(
                backend=backend,
                values=values,
                system_prompt=system_prompt,
                max_retries=config.max_retries,
                retry_delay=config.retry_delay_seconds,
                batch_idx=batch_idx,
                total_batches=total_batches,
            )
            done: list[RawLine] = []
            for representative, dst in zip(batch, translated):
                for entry in groups[representative.value or ""]:
                    entry.translated = dst
                    if entry.key:
                        cache[entry.key] = {"src": entry.value or "", "dst": dst}
                    done.append(entry)
            save_cache(cache_path, cache)
            assemble_entries(done, config.output_path, append=True)
            bar.update(len(done))
            bar.set_postfix(batch=f"{batch_idx + 1}/{total_batches}")

    save_cache(cache_path, cache)
    logger.info("Cache saved to %s", cache_path)

    # Rewrite output in original file order (incremental appends above are for crash recovery)
    final_entries = [line for line in parsed.lines if line.kind == LineKind.ENTRY]
    assemble_entries(final_entries, config.output_path, append=False)

    new_version = bump_version(
        config.output_dir, config.version, config.target_lang_code
    )
    logger.info(
        "Version bumped to %s (%s/%s)",
        new_version,
        config.version,
        config.target_lang_code,
    )

    return config.output_path


def _split_by_cache(
    entries: list[RawLine], cache: Cache
) -> tuple[list[RawLine], list[RawLine]]:
    """Return (cache_hits, cache_misses).

    A hit means the key exists in cache AND the English source hasn't changed.
    A changed source value counts as a miss so it gets re-translated.
    """
    hits: list[RawLine] = []
    misses: list[RawLine] = []

    for entry in entries:
        key = entry.key or ""
        cached = cache.get(key)
        if cached and cached["src"] == entry.value:
            hits.append(entry)
        else:
            misses.append(entry)

    return hits, misses


def _translate_with_retry(
    backend: TranslatorBackend,
    values: list[str],
    system_prompt: str,
    max_retries: int,
    retry_delay: float,
    batch_idx: int,
    total_batches: int,
) -> list[str]:
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(
                "Batch %d/%d — attempt %d", batch_idx + 1, total_batches, attempt
            )
            return backend.translate_batch(values, system_prompt)
        except ContextTooLongError:
            if len(values) == 1:
                chunks = _split_text(values[0])
                if len(chunks) == 1:
                    logger.warning(
                        "Batch %d/%d: single entry could not be split further, keeping original",
                        batch_idx + 1,
                        total_batches,
                    )
                    return values
                logger.warning(
                    "Batch %d/%d: single entry too long, splitting into %d text chunks",
                    batch_idx + 1,
                    total_batches,
                    len(chunks),
                )
                translated_chunks = _translate_with_retry(
                    backend,
                    chunks,
                    system_prompt,
                    max_retries,
                    retry_delay,
                    batch_idx,
                    total_batches,
                )
                return ["".join(translated_chunks)]
            half = len(values) // 2
            logger.warning(
                "Batch %d/%d too long (%d entries), splitting in half",
                batch_idx + 1,
                total_batches,
                len(values),
            )
            left = _translate_with_retry(
                backend,
                values[:half],
                system_prompt,
                max_retries,
                retry_delay,
                batch_idx,
                total_batches,
            )
            right = _translate_with_retry(
                backend,
                values[half:],
                system_prompt,
                max_retries,
                retry_delay,
                batch_idx,
                total_batches,
            )
            return left + right
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Batch %d/%d attempt %d failed: %s",
                batch_idx + 1,
                total_batches,
                attempt,
                exc,
            )
            if attempt < max_retries:
                time.sleep(retry_delay)

    raise RuntimeError(
        f"Batch {batch_idx + 1}/{total_batches} failed after {max_retries} attempts"
    ) from last_exc


# ~2000 chars ≈ 500 tokens — safe chunk size for a single translation call
_CHUNK_SIZE = 2000


def _split_text(text: str) -> list[str]:
    """Split a long string into translatable chunks at safe boundaries.

    Priority: \\n → sentence boundary (. ) → space → hard cut.
    Chunks are designed to be rejoined with "".join().
    """
    if len(text) <= _CHUNK_SIZE:
        return [text]

    mid = len(text) // 2
    search_start = len(text) // 4
    search_end = search_start * 3

    best = -1

    # Priority 1: \n escape sequence
    for m in re.finditer(r"\\n", text):
        candidate = m.end()
        if search_start <= candidate <= search_end:
            if best == -1 or abs(candidate - mid) < abs(best - mid):
                best = candidate

    # Priority 2: sentence boundary ". "
    if best == -1:
        for m in re.finditer(r"\.\s", text):
            candidate = m.end()
            if search_start <= candidate <= search_end:
                if best == -1 or abs(candidate - mid) < abs(best - mid):
                    best = candidate

    # Priority 3: any space
    if best == -1:
        for m in re.finditer(r"\s", text):
            candidate = m.end()
            if search_start <= candidate <= search_end:
                if best == -1 or abs(candidate - mid) < abs(best - mid):
                    best = candidate

    # Priority 4: hard cut at middle
    if best == -1:
        best = mid

    left, right = text[:best], text[best:]
    return _split_text(left) + _split_text(right)
