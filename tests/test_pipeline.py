import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

from translator.backends.base import TranslatorBackend
from translator.config import Config
from translator.pipeline import run

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
