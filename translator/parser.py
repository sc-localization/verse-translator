from __future__ import annotations

from pathlib import Path

from translator.models import LineKind, ParsedIni, RawLine


def parse(path: Path) -> ParsedIni:
    """Parse a global.ini file, preserving every line for round-trip output."""
    result = ParsedIni()
    text = path.read_text(encoding="utf-8-sig")  # strip BOM if present

    for raw in text.splitlines():
        result.lines.append(_classify(raw))

    return result


def _classify(raw: str) -> RawLine:
    stripped = raw.strip()

    if not stripped:
        return RawLine(kind=LineKind.EMPTY, raw=raw)

    if stripped.startswith(";"):
        return RawLine(kind=LineKind.COMMENT, raw=raw)

    if stripped.startswith("[") and stripped.endswith("]"):
        return RawLine(kind=LineKind.SECTION, raw=raw)

    eq = raw.find("=")
    if eq != -1:
        key = raw[:eq]
        value = raw[eq + 1 :]
        return RawLine(kind=LineKind.ENTRY, raw=raw, key=key, value=value)

    return RawLine(kind=LineKind.COMMENT, raw=raw)


def assemble(parsed: ParsedIni, output_path: Path) -> None:
    """Write only translated key=value entries to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{line.key}={line.translated}"
        for line in parsed.lines
        if line.kind == LineKind.ENTRY and line.translated is not None
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
