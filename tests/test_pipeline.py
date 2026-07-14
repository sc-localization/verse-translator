import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

from translator.backends.base import TranslatorBackend
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


def test_split_text_never_cuts_variables():
    sentence = "The quick brown fox jumps over the lazy dog. "
    text = (sentence * 20 + "~mission(alpha|SomeLongContract) ") * 5

    chunks = _split_text(text)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    total_vars = sum(len(extract_variables(c)) for c in chunks)
    assert total_vars == len(extract_variables(text))


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
