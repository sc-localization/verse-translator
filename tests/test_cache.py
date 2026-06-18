import json
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

from translator.backends.base import TranslatorBackend
from translator.cache import cache_path_for
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
    data = json.loads(cache_file.read_text())
    assert data["ui_loading"]["src"] == "Loading screen"
    assert data["ui_loading"]["dst"] == "Экран загрузки"
