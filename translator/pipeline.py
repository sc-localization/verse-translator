from __future__ import annotations

import logging
import re
import time
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from translator.backends.base import (
    BatchSizeMismatchError,
    ContextTooLongError,
    TranslatorBackend,
)
from translator.backends.lmstudio import LMStudioBackend
from translator.batcher import DEFAULT_MAX_CHARS, make_batches
from translator.cache import (
    Cache,
    cache_path_for,
)
from translator.cache import (
    append as append_cache,
)
from translator.cache import (
    load as load_cache,
)
from translator.cache import (
    save as save_cache,
)
from translator.config import Config
from translator.models import (
    LineKind,
    ParsedIni,
    RawLine,
    extract_variables,
    variable_spans,
)
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

    max_chars = _max_chars_for(backend, system_prompt)
    batches = make_batches(unique, config.batch_size, max_chars)
    total_batches = len(batches)

    try:
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
                    max_chars=max_chars,
                )
                translated = _repair_broken_variables(
                    backend=backend,
                    values=values,
                    translated=translated,
                    system_prompt=system_prompt,
                    max_retries=config.max_retries,
                    retry_delay=config.retry_delay_seconds,
                    batch_idx=batch_idx,
                    total_batches=total_batches,
                    max_chars=max_chars,
                )
                done: list[RawLine] = []
                new_records: Cache = {}
                for representative, dst in zip(batch, translated):
                    # dst == src means every attempt fell back to the source text
                    # (see _repair_broken_variables / _translate_in_chunks) — do
                    # not cache it, so the entry is retried on the next run
                    # instead of being pinned to English forever.
                    fallback = dst == (representative.value or "")
                    for entry in groups[representative.value or ""]:
                        entry.translated = dst
                        if entry.key and not fallback:
                            new_records[entry.key] = {
                                "src": entry.value or "",
                                "dst": dst,
                            }
                        done.append(entry)
                cache.update(new_records)
                append_cache(cache_path, new_records)
                assemble_entries(done, config.output_path, append=True)
                bar.update(len(done))
                bar.set_postfix(batch=f"{batch_idx + 1}/{total_batches}")
    except KeyboardInterrupt:
        # Every batch above is only appended to cache/output *after* it
        # finishes translating and validating — so nothing here is
        # half-written. The in-flight batch is simply dropped and gets
        # retranslated on the next run; everything before it is durable.
        save_cache(cache_path, cache)
        tqdm.write(
            f"\nInterrupted — progress saved "
            f"({batch_idx}/{total_batches} batches this run). "
            f"Rerun the same command to resume; already-translated entries "
            f"are cached and won't be retranslated."
        )
        raise

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


def _max_chars_for(backend: TranslatorBackend, system_prompt: str) -> int:
    """Source-chars budget per request, derived from the model context window.

    System prompt tokens and the reserved output tokens share the SAME
    context window as the input batch (LM Studio truncates generation at
    the total context length, not at max_output_tokens) — so both must be
    subtracted from the budget before converting the remainder to chars.
    ~0.75 chars per token is a conservative (i.e. token-dense) estimate;
    it still assumes prose-like content and can be optimistic for
    numeric-heavy strings, hence the extra safety margin below.
    """
    ctx = getattr(backend, "context_length", None)
    if not ctx:
        return DEFAULT_MAX_CHARS
    max_output = getattr(backend, "max_output_tokens", ctx // 2)
    system_prompt_tokens = len(system_prompt) // 3  # ~3 chars/token, conservative
    safety_margin = 100
    input_token_budget = max(
        ctx - max_output - system_prompt_tokens - safety_margin, 256
    )
    return int(input_token_budget * 0.75)


def _translate_with_retry(
    backend: TranslatorBackend,
    values: list[str],
    system_prompt: str,
    max_retries: int,
    retry_delay: float,
    batch_idx: int,
    total_batches: int,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    # Split oversized single entries upfront instead of burning a doomed generation
    if len(values) == 1 and len(values[0]) > max_chars:
        return _translate_in_chunks(
            backend,
            values[0],
            system_prompt,
            max_retries,
            retry_delay,
            batch_idx,
            total_batches,
            max_chars,
        )

    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(
                "Batch %d/%d — attempt %d", batch_idx + 1, total_batches, attempt
            )
            translated = backend.translate_batch(values, system_prompt)
            return [_normalize_newlines(t) for t in translated]
        except BatchSizeMismatchError as exc:
            if len(values) > 1:
                # The model merged or split entries. Temperature is 0, so an
                # identical request gives an identical answer — reshape the
                # batch instead of burning retries on the same prompt.
                logger.warning(
                    "Batch %d/%d: %s (%d entries), splitting in half",
                    batch_idx + 1,
                    total_batches,
                    exc,
                    len(values),
                )
                return _translate_halves(
                    backend,
                    values,
                    system_prompt,
                    max_retries,
                    retry_delay,
                    batch_idx,
                    total_batches,
                    max_chars,
                )
            # A single entry can't be split further here; retry, then fall back.
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
            continue
        except ContextTooLongError as exc:
            if len(values) == 1 and len(values[0]) <= max_chars:
                # Not a real context overflow (the entry fits the budget) —
                # the model returned malformed/truncated JSON. Retry like any
                # other transient failure instead of giving up immediately;
                # chunk-splitting a short entry can't fix bad JSON output.
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
                continue
            if len(values) == 1:
                return _translate_in_chunks(
                    backend,
                    values[0],
                    system_prompt,
                    max_retries,
                    retry_delay,
                    batch_idx,
                    total_batches,
                    max_chars,
                )
            logger.warning(
                "Batch %d/%d too long (%d entries), splitting in half",
                batch_idx + 1,
                total_batches,
                len(values),
            )
            return _translate_halves(
                backend,
                values,
                system_prompt,
                max_retries,
                retry_delay,
                batch_idx,
                total_batches,
                max_chars,
            )
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

    if isinstance(last_exc, _MODEL_OUTPUT_ERRORS):
        # The model answered, it just answered badly. Losing a 22-hour run over
        # one unparseable reply is worse than shipping this batch in English:
        # dst == src is not cached, so the next run retries it (see run()).
        logger.error(
            "Batch %d/%d failed after %d attempts (%s) — keeping source text, "
            "will retry on the next run",
            batch_idx + 1,
            total_batches,
            max_retries,
            last_exc,
        )
        return list(values)

    # Transport/server failures (LM Studio down, model unloaded) would silently
    # turn the whole run into a copy of the English file — abort instead.
    raise RuntimeError(
        f"Batch {batch_idx + 1}/{total_batches} failed after {max_retries} attempts"
    ) from last_exc


# Errors that mean "bad model output" rather than "backend unreachable"
_MODEL_OUTPUT_ERRORS = (BatchSizeMismatchError, ContextTooLongError, ValueError)


def _translate_halves(
    backend: TranslatorBackend,
    values: list[str],
    system_prompt: str,
    max_retries: int,
    retry_delay: float,
    batch_idx: int,
    total_batches: int,
    max_chars: int,
) -> list[str]:
    """Translate a batch as two independent halves, preserving order."""
    half = len(values) // 2
    left = _translate_with_retry(
        backend,
        values[:half],
        system_prompt,
        max_retries,
        retry_delay,
        batch_idx,
        total_batches,
        max_chars,
    )
    right = _translate_with_retry(
        backend,
        values[half:],
        system_prompt,
        max_retries,
        retry_delay,
        batch_idx,
        total_batches,
        max_chars,
    )
    return left + right


def _normalize_newlines(text: str) -> str:
    """Turn real newlines from the model back into the literal \\n escape.

    Values in global.ini are single-line: the file stores the two-character
    escape, but models routinely emit a real newline for it in JSON output.
    """
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _variables_preserved(src: str, dst: str) -> bool:
    return sorted(extract_variables(src)) == sorted(extract_variables(dst))


def _repair_broken_variables(
    backend: TranslatorBackend,
    values: list[str],
    translated: list[str],
    system_prompt: str,
    max_retries: int,
    retry_delay: float,
    batch_idx: int,
    total_batches: int,
    max_chars: int,
) -> list[str]:
    """Re-translate entries whose game variables got corrupted.

    If the retry is corrupted too, keep the original source text — broken
    variables crash or garble the game, an untranslated line does not.
    """
    repaired = list(translated)

    for i, (src, dst) in enumerate(zip(values, translated)):
        if _variables_preserved(src, dst):
            continue
        src_vars = Counter(extract_variables(src))
        dst_vars = Counter(extract_variables(dst))
        logger.warning(
            "Batch %d/%d: game variables corrupted (lost: %s, added: %s), retrying entry",
            batch_idx + 1,
            total_batches,
            dict(src_vars - dst_vars) or "-",
            dict(dst_vars - src_vars) or "-",
        )
        retry = _translate_with_retry(
            backend,
            [src],
            system_prompt,
            max_retries,
            retry_delay,
            batch_idx,
            total_batches,
            max_chars,
        )[0]
        if _variables_preserved(src, retry):
            repaired[i] = retry
        else:
            logger.warning(
                "Batch %d/%d: variables still corrupted after retry, keeping original",
                batch_idx + 1,
                total_batches,
            )
            repaired[i] = src

    return repaired


def _translate_in_chunks(
    backend: TranslatorBackend,
    text: str,
    system_prompt: str,
    max_retries: int,
    retry_delay: float,
    batch_idx: int,
    total_batches: int,
    max_chars: int,
) -> list[str]:
    """Translate one oversized entry as text chunks, rejoined afterwards."""
    # A small model context can push max_chars below the default chunk size;
    # without this, entries between max_chars and _CHUNK_SIZE never split
    # and silently ship untranslated (they're too big for one request but
    # "not big enough" to trigger splitting).
    chunks = _split_text(text, chunk_size=min(_CHUNK_SIZE, max_chars))
    if len(chunks) == 1:
        logger.warning(
            "Batch %d/%d: single entry could not be split further, keeping original",
            batch_idx + 1,
            total_batches,
        )
        return [text]

    logger.warning(
        "Batch %d/%d: entry of %d chars translated as %d text chunks",
        batch_idx + 1,
        total_batches,
        len(text),
        len(chunks),
    )
    translated: list[str] = []
    for group in _pack_chunks(chunks, max_chars):
        group_translated = _translate_with_retry(
            backend,
            group,
            system_prompt,
            max_retries,
            retry_delay,
            batch_idx,
            total_batches,
            max_chars,
        )
        # Repair per chunk: a retry costs one chunk, not the whole entry
        translated += _repair_broken_variables(
            backend=backend,
            values=group,
            translated=group_translated,
            system_prompt=system_prompt,
            max_retries=max_retries,
            retry_delay=retry_delay,
            batch_idx=batch_idx,
            total_batches=total_batches,
            max_chars=max_chars,
        )
    return ["".join(translated)]


def _pack_chunks(chunks: list[str], max_chars: int) -> list[list[str]]:
    """Greedily group chunks so each request stays within the chars budget."""
    groups: list[list[str]] = []
    current: list[str] = []
    current_chars = 0

    for chunk in chunks:
        if current and current_chars + len(chunk) > max_chars:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += len(chunk)

    if current:
        groups.append(current)

    return groups


# ~2000 chars ≈ 500 tokens — safe chunk size for a single translation call
_CHUNK_SIZE = 2000


def _split_text(text: str, chunk_size: int = _CHUNK_SIZE) -> list[str]:
    """Split a long string into translatable chunks at safe boundaries.

    Priority: \\n → sentence boundary (. ) → space → hard cut.
    Boundaries never fall inside a game variable — a cut ~func() or <tag>
    cannot be preserved by translation. Chunks rejoin with "".join().
    """
    if len(text) <= chunk_size:
        return [text]

    spans = variable_spans(text)

    def outside_variables(candidate: int) -> bool:
        return not any(start < candidate < end for start, end in spans)

    mid = len(text) // 2
    search_start = len(text) // 4
    search_end = search_start * 3

    best = -1

    # Boundary priority: \n escape → sentence end ". " → any space
    for pattern in (r"\\n", r"\.\s", r"\s"):
        for m in re.finditer(pattern, text):
            candidate = m.end()
            if (
                search_start <= candidate <= search_end
                and outside_variables(candidate)
                and (best == -1 or abs(candidate - mid) < abs(best - mid))
            ):
                best = candidate
        if best != -1:
            break

    # Fallback: hard cut at middle, nudged out of a variable if needed
    if best == -1:
        best = mid
        for start, end in spans:
            if start < best < end:
                best = end if end < len(text) else start
                break
        if best <= 0 or best >= len(text):
            # The nudge couldn't escape the variable (it spans the whole
            # midsection) — cutting here would still land inside it, which
            # breaks this function's contract. Give up splitting rather than
            # cut a variable in half.
            return [text]

    left, right = text[:best], text[best:]
    return _split_text(left, chunk_size) + _split_text(right, chunk_size)
