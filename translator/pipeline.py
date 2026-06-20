from __future__ import annotations

import logging
import time
from pathlib import Path

from tqdm import tqdm

from translator.backends.base import TranslatorBackend
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
from translator.models import ParsedIni, RawLine
from translator.parser import assemble, parse
from translator.versioning import bump_version

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional video game localization translator.
Translate the Star Citizen UI text from {source_lang} into {target_lang}.

Rules:
- Translate only human-readable text. Do NOT translate variables: ~func(), @tag, %ls, {{0}}, \\n, <tags>.
- Keep the sci-fi tone and atmosphere of the original.
- Preserve capitalisation style (ALL CAPS stays ALL CAPS, Title Case stays Title Case).
- Ship names, star systems, and corporation names should remain untranslated unless a well-known official translation exists.
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

    logger.info(
        "Entries: %d total, %d cached, %d to translate (backend: %s)",
        len(translatable),
        len(hits),
        len(misses),
        backend.name,
    )

    # Apply cached translations immediately
    for entry in hits:
        entry.translated = cache[entry.key or ""]["dst"]

    # Translate only the new/changed entries
    if misses:
        system_prompt = build_system_prompt(config)
        batches = make_batches(misses, config.batch_size)
        total_batches = len(batches)

        with tqdm(total=len(misses), unit="entry", desc="Translating") as bar:
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
                for entry, dst in zip(batch, translated):
                    entry.translated = dst
                    if entry.key:
                        cache[entry.key] = {"src": entry.value or "", "dst": dst}
                save_cache(cache_path, cache)
                assemble(parsed, config.output_path)
                bar.update(len(batch))
                bar.set_postfix(batch=f"{batch_idx + 1}/{total_batches}")

    save_cache(cache_path, cache)
    logger.info("Cache saved to %s", cache_path)

    logger.info("Writing output to %s", config.output_path)
    assemble(parsed, config.output_path)

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
