import tempfile
import textwrap
from pathlib import Path

from translator.models import LineKind
from translator.parser import assemble_entries, parse

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


def test_translatable_skips_pure_number_fluff_but_keeps_prose_with_numbers():
    ini = textwrap.dedent("""\
        item_fluff=0.5 1.2 2.4 4.8
        item_prose=Thruster output curve: 0.5 1.2 2.4 4.8
    """)
    path = _write_tmp(ini)
    result = parse(path)

    translatable_keys = {e.key for e in result.translatable_entries()}
    assert "item_fluff" not in translatable_keys
    assert "item_prose" in translatable_keys


def test_round_trip():
    path = _write_tmp(SAMPLE_INI)
    result = parse(path)

    with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as out_f:
        out_path = Path(out_f.name)

    assemble_entries(result.entries, out_path)
    written = out_path.read_text(encoding="utf-8")

    assert "ui_loading=Loading..." in written
    assert "ui_hello=Hello pilot" in written
    assert "ui_var=~mission(foo)" in written


def test_overwrite_with_no_entries_truncates_stale_file():
    # A non-append call must always recreate the file, even with zero
    # entries, so it can't leave a previous run's stale content behind.
    out_path = Path(tempfile.mktemp(suffix=".ini"))
    out_path.write_text("stale content from a previous run", encoding="utf-8")

    assemble_entries([], out_path, append=False)

    assert out_path.read_text(encoding="utf-8") == ""


def test_append_with_no_entries_is_a_noop():
    out_path = Path(tempfile.mktemp(suffix=".ini"))
    out_path.write_text("existing content", encoding="utf-8")

    assemble_entries([], out_path, append=True)

    assert out_path.read_text(encoding="utf-8") == "existing content"
