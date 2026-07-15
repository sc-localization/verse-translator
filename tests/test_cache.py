import json
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

from translator.backends.base import TranslatorBackend
from translator.cache import cache_path_for
from translator.cache import load as load_cache
from translator.config import Config
from translator.pipeline import run

INITIAL_INI = textwrap.dedent("""\
    ui_loading=Loading screen
    ui_hello=Hello pilot
""")

UPDATED_INI = textwrap.dedent("""\
    ui_loading=Loading screen
    ui_hello=Hello pilot
    ui_new=New feature unlocked
""")

CHANGED_INI = textwrap.dedent("""\
    ui_loading=Loading screen updated
    ui_hello=Hello pilot
""")


def _write_tmp(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


def _make_config(input_path: Path, out_dir: Path) -> Config:
    return Config(
        input_path=input_path, output_dir=out_dir, version="TEST", batch_size=10
    )


def test_second_run_uses_cache():
    """Second run on same file should not call the backend at all."""
    input_path = _write_tmp(INITIAL_INI)
    out_dir = Path(tempfile.mkdtemp())
    config = _make_config(input_path, out_dir)

    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]

    run(config, backend)
    assert backend.translate_batch.call_count == 1

    # Second run — nothing changed
    run(config, backend)
    assert backend.translate_batch.call_count == 1  # still 1, cache hit


def test_new_lines_only_translated():
    """Adding new lines should translate only the new ones."""
    out_dir = Path(tempfile.mkdtemp())

    # First run
    input_path = _write_tmp(INITIAL_INI)
    config = _make_config(input_path, out_dir)
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]
    run(config, backend)

    # Second run with a new line added
    input_path2 = _write_tmp(UPDATED_INI)
    config2 = _make_config(input_path2, out_dir)
    backend.translate_batch.return_value = ["Новая функция разблокирована"]
    run(config2, backend)

    assert backend.translate_batch.call_count == 2
    sent_values = backend.translate_batch.call_args[0][0]
    assert sent_values == ["New feature unlocked"]


def test_changed_line_retranslated():
    """A line whose English source changed must be re-translated."""
    out_dir = Path(tempfile.mkdtemp())

    input_path = _write_tmp(INITIAL_INI)
    config = _make_config(input_path, out_dir)
    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]
    run(config, backend)

    input_path2 = _write_tmp(CHANGED_INI)
    config2 = _make_config(input_path2, out_dir)
    backend.translate_batch.return_value = ["Экран загрузки обновлён"]
    run(config2, backend)

    assert backend.translate_batch.call_count == 2
    sent_values = backend.translate_batch.call_args[0][0]
    assert sent_values == ["Loading screen updated"]


def test_cache_persisted_to_disk():
    input_path = _write_tmp(INITIAL_INI)
    out_dir = Path(tempfile.mkdtemp())
    config = _make_config(input_path, out_dir)

    backend = MagicMock(spec=TranslatorBackend)
    backend.name = "mock"
    backend.translate_batch.return_value = ["Экран загрузки", "Привет, пилот"]
    run(config, backend)

    cache_file = cache_path_for(config.output_path)
    assert cache_file.exists()
    data = load_cache(cache_file)
    assert data["ui_loading"]["src"] == "Loading screen"
    assert data["ui_loading"]["dst"] == "Экран загрузки"


def test_load_skips_truncated_trailing_line():
    """A crash mid-append can leave a partial final JSONL line; load() must
    not brick every future run over it — it should drop the bad line."""
    cache_file = Path(tempfile.mktemp(suffix=".jsonl"))
    good = json.dumps({"key": "ui_hello", "src": "Hello pilot", "dst": "Привет"})
    cache_file.write_text(good + "\n" + '{"key": "ui_loa', encoding="utf-8")

    data = load_cache(cache_file)

    assert data == {"ui_hello": {"src": "Hello pilot", "dst": "Привет"}}


def test_legacy_cache_is_migrated_to_jsonl_on_load():
    """The legacy .json cache must survive an interrupted first run on the
    new JSONL format — it should be migrated to .jsonl immediately on load,
    not only after a full run completes."""
    out_dir = Path(tempfile.mkdtemp())
    jsonl_path = out_dir / ".translation_cache.jsonl"
    legacy_path = jsonl_path.with_suffix(".json")
    legacy_path.write_text(
        json.dumps({"ui_hello": {"src": "Hello pilot", "dst": "Привет"}}),
        encoding="utf-8",
    )

    data = load_cache(jsonl_path)

    assert data == {"ui_hello": {"src": "Hello pilot", "dst": "Привет"}}
    assert jsonl_path.exists()
    # Re-reading from disk (as a fresh process after a crash would) must see
    # the migrated data without the legacy file.
    assert load_cache(jsonl_path) == data
