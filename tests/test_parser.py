import tempfile
import textwrap
from pathlib import Path

from translator.models import LineKind
from translator.parser import assemble, parse

SAMPLE_INI = textwrap.dedent("""\
    ; Star Citizen Localization

    [General]
    ui_loading=Loading...
    ui_empty=
    ui_var=~mission(foo)
    ui_mixed=Quantum drive: ~item(qd)
    ui_hello=Hello pilot
""")


def _write_tmp(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


def test_parse_line_kinds():
    path = _write_tmp(SAMPLE_INI)
    result = parse(path)

    kinds = [line.kind for line in result.lines]
    assert LineKind.COMMENT in kinds
    assert LineKind.SECTION in kinds
    assert LineKind.ENTRY in kinds
    assert LineKind.EMPTY in kinds


def test_entries_have_key_value():
    path = _write_tmp(SAMPLE_INI)
    result = parse(path)

    entries = result.entries
    assert any(e.key == "ui_loading" and e.value == "Loading..." for e in entries)


def test_translatable_skips_empty_and_pure_vars():
    path = _write_tmp(SAMPLE_INI)
    result = parse(path)

    translatable_keys = {e.key for e in result.translatable_entries()}
    assert "ui_loading" in translatable_keys
    assert "ui_hello" in translatable_keys
    assert "ui_mixed" in translatable_keys
    assert "ui_empty" not in translatable_keys
    assert "ui_var" not in translatable_keys  # pure ~mission()


def test_round_trip():
    path = _write_tmp(SAMPLE_INI)
    result = parse(path)

    with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as out_f:
        out_path = Path(out_f.name)

    assemble(result, out_path)
    written = out_path.read_text(encoding="utf-8")

    assert "ui_loading=Loading..." in written
    assert "[General]" in written
    assert "; Star Citizen Localization" in written
