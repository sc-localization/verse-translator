import json
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from translator.backends.base import (
    BatchSizeMismatchError,
    ContextTooLongError,
    TranslatorBackend,
)
from translator.cache import cache_path_for
from translator.cache import load as load_cache
from translator.config import Config
from translator.models import extract_variables
from translator.pipeline import _split_text, run

SAMPLE_INI = textwrap.dedent("""\
    ui_loading=Loading screen
    ui_hello=Hello pilot
    ui_var=~mission(foo)
""")


def _write_tmp(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


def test_pipeline_calls_backend_and_writes_output():
    input_path = _write_tmp(SAMPLE_INI)
    out_dir = Path(tempfile.mkdtemp())

    config = Config(
        input_path=input_path,
        output_dir=out_dir,
        version="TEST",
        batch_size=10,
    )

    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]

    output_path = run(config, backend)

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "ui_loading=Экран загрузки" in content
    assert "ui_hello=Привет, пилот" in content
    # pure variable line must be untouched
    assert "ui_var=~mission(foo)" in content

    # backend was called once (2 translatable entries fit in one batch of 10)
    backend.translate_batch.assert_called_once()
    args = backend.translate_batch.call_args[0]
    assert args[0] == ["Loading screen", "Hello pilot"]


VAR_INI = "ui_target=Target: ~mission(foo)\n"


def _var_config(input_path: Path) -> Config:
    return Config(
        input_path=input_path,
        output_dir=Path(tempfile.mkdtemp()),
        version="TEST",
        batch_size=10,
    )


def test_corrupted_variable_retried_then_fixed():
    config = _var_config(_write_tmp(VAR_INI))
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = [
        ["Цель: ~миссия(foo)"],  # variable translated — corrupted
        ["Цель: ~mission(foo)"],  # retry preserves it
    ]

    output_path = run(config, backend)

    assert backend.translate_batch.call_count == 2
    assert "ui_target=Цель: ~mission(foo)" in output_path.read_text(encoding="utf-8")


def test_corrupted_variable_falls_back_to_source():
    config = _var_config(_write_tmp(VAR_INI))
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = [
        ["Цель: ~миссия(foo)"],
        ["Цель: ~миссия(foo)"],  # retry corrupted too — keep English
    ]

    output_path = run(config, backend)

    assert backend.translate_batch.call_count == 2
    assert "ui_target=Target: ~mission(foo)" in output_path.read_text(encoding="utf-8")


def test_real_newlines_normalized_back_to_escapes():
    # Source holds the literal two-char \n escape; the mock model returns
    # a real newline for it, as local models often do in JSON output
    config = _var_config(_write_tmp("ui_multi=First line\\nSecond line\n"))
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Первая строка\nВторая строка"]

    output_path = run(config, backend)

    backend.translate_batch.assert_called_once()  # no corruption retry
    content = output_path.read_text(encoding="utf-8")
    assert "ui_multi=Первая строка\\nВторая строка" in content


def test_fallback_to_source_is_not_cached():
    # A permanently-corrupted variable falls back to the English source; that
    # fallback must not be cached, so the entry is retried on the next run
    # instead of being pinned to English forever.
    config = _var_config(_write_tmp(VAR_INI))
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = [
        ["Цель: ~миссия(foo)"],
        ["Цель: ~миссия(foo)"],  # retry corrupted too — keep English
    ]

    run(config, backend)

    cache = load_cache(cache_path_for(config.output_path))
    assert "ui_target" not in cache


def test_malformed_json_is_retried_before_falling_back():
    # A single short entry whose response fails JSON decoding raises
    # ContextTooLongError from the backend, but it isn't a real context
    # overflow (the entry fits comfortably) — it must be retried like any
    # other transient failure, not immediately handed to chunk-splitting.
    config = _var_config(_write_tmp(VAR_INI))
    config.retry_delay_seconds = 0
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = [
        ContextTooLongError("JSON decoding failed: bad token"),
        ["Цель: ~mission(foo)"],
    ]

    output_path = run(config, backend)

    assert backend.translate_batch.call_count == 2
    assert "ui_target=Цель: ~mission(foo)" in output_path.read_text(encoding="utf-8")


def test_batch_size_mismatch_splits_instead_of_retrying():
    # The model merged/split entries. At temperature 0 the same prompt gives
    # the same broken answer, so the batch must be reshaped, not repeated.
    config = _var_config(_write_tmp("a=Alpha\nb=Beta\n"))
    config.retry_delay_seconds = 0
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = [
        BatchSizeMismatchError("Expected 2 translations, got 3"),
        ["Альфа"],  # left half
        ["Бета"],  # right half
    ]

    output_path = run(config, backend)

    assert backend.translate_batch.call_count == 3
    assert [c[0][0] for c in backend.translate_batch.call_args_list] == [
        ["Alpha", "Beta"],
        ["Alpha"],
        ["Beta"],
    ]
    content = output_path.read_text(encoding="utf-8")
    assert "a=Альфа" in content
    assert "b=Бета" in content


def test_unsplittable_bad_response_keeps_source_without_crashing():
    # A single entry the model never answers correctly must not abort the run
    config = _var_config(_write_tmp(VAR_INI))
    config.retry_delay_seconds = 0
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = BatchSizeMismatchError(
        "Expected 1 translations, got 2"
    )

    output_path = run(config, backend)

    assert backend.translate_batch.call_count == config.max_retries
    assert "ui_target=Target: ~mission(foo)" in output_path.read_text(encoding="utf-8")
    # not cached — the entry is retried on the next run
    assert "ui_target" not in load_cache(cache_path_for(config.output_path))


def test_backend_unreachable_still_aborts_the_run():
    # Transport failures must not degrade into a full English copy
    config = _var_config(_write_tmp(VAR_INI))
    config.retry_delay_seconds = 0
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.side_effect = ConnectionError("connection refused")

    with pytest.raises(RuntimeError, match="failed after"):
        run(config, backend)


def test_fully_cached_run_still_bumps_version():
    # A resume/regenerate run where every entry is already cached must still
    # bump versions.json, matching the unconditional bump on a normal run.
    from translator.versioning import versions_path_for

    input_path = _write_tmp(SAMPLE_INI)
    out_dir = Path(tempfile.mkdtemp())
    config = Config(
        input_path=input_path, output_dir=out_dir, version="TEST", batch_size=10
    )
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]

    run(config, backend)
    versions_file = versions_path_for(out_dir)
    first_version = json.loads(versions_file.read_text())["TEST"]["languages"]["ru"][
        "version"
    ]

    # Second run: nothing changed, every entry is a cache hit.
    run(config, backend)
    second_version = json.loads(versions_file.read_text())["TEST"]["languages"]["ru"][
        "version"
    ]

    assert second_version != first_version


def test_split_text_never_cuts_variables():
    sentence = "The quick brown fox jumps over the lazy dog. "
    text = (sentence * 20 + "~mission(alpha|SomeLongContract) ") * 5

    chunks = _split_text(text)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    total_vars = sum(len(extract_variables(c)) for c in chunks)
    assert total_vars == len(extract_variables(text))


def test_split_text_giant_variable_spanning_midsection_is_not_cut():
    # A single game variable bigger than the chunk size leaves no valid cut
    # point outside it — splitting must be refused rather than cut through it.
    var = "~mission(" + "x" * 3990 + ")"

    chunks = _split_text(var)

    assert chunks == [var]
    assert extract_variables("".join(chunks)) == extract_variables(var)


def test_split_text_hard_cut_avoids_variable():
    # No spaces or sentence ends anywhere — forces the hard-cut fallback
    # onto a variable sitting exactly at the middle
    var = "~mission(" + "x" * 50 + ")"
    half = (4000 - len(var)) // 2
    text = "a" * half + var + "b" * half

    chunks = _split_text(text)

    assert "".join(chunks) == text
    total_vars = sum(len(extract_variables(c)) for c in chunks)
    assert total_vars == len(extract_variables(text))
