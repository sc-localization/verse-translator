from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class LineKind(Enum):
    ENTRY = auto()  # key=value
    COMMENT = auto()  # ; ...
    EMPTY = auto()  # blank line
    SECTION = auto()  # [section]


@dataclass
class RawLine:
    """Preserves original file line for round-trip fidelity."""

    kind: LineKind
    raw: str  # original text (no trailing newline)
    key: Optional[str] = None  # only for ENTRY
    value: Optional[str] = None  # only for ENTRY
    translated: Optional[str] = None  # filled during pipeline

    def output(self) -> str:
        if self.kind == LineKind.ENTRY:
            v = self.translated if self.translated is not None else self.value
            return f"{self.key}={v}"

        return self.raw


@dataclass
class ParsedIni:
    lines: list[RawLine] = field(default_factory=list)

    @property
    def entries(self) -> list[RawLine]:
        return [line for line in self.lines if line.kind == LineKind.ENTRY]

    def translatable_entries(self) -> list[RawLine]:
        return [e for e in self.entries if _is_translatable(e.value or "")]


# Patterns that mark a value as non-translatable
_SKIP_PREFIXES = ("~", "@")
_SKIP_ONLY_VARS = True  # if value has no Latin/Cyrillic words after stripping vars

_VAR_RE = re.compile(
    r"(~\w+\([^)]*\)"  # ~mission(...)
    r"|@\w+"  # @ui_label
    r"|%ls\b"  # %ls
    r"|\\n"  # escape sequences
    r"|\{\d+\}"  # {0} positional
    r"|<[^\s<>]+>)"  # <tag> (no whitespace/newlines inside — real tags are short IDs)
)

# Matches SC fluff data: sequences of decimal numbers separated by spaces
_FLUFF_RE = re.compile(r"\d+\.\d+(?:\s+\d+\.\d+){3,}")


def extract_variables(value: str) -> list[str]:
    """Game variables/placeholders that must survive translation unchanged."""
    return _VAR_RE.findall(value)


def variable_spans(value: str) -> list[tuple[int, int]]:
    """(start, end) positions of game variables; text must not be cut inside them."""
    return [m.span() for m in _VAR_RE.finditer(value)]


def _is_translatable(value: str) -> bool:
    if not value.strip():
        return False

    stripped = _VAR_RE.sub("", value).strip()

    if not stripped:
        return False

    fluff_match = _FLUFF_RE.search(stripped)
    # Only skip when the numeric run makes up most of the value — otherwise
    # prose that happens to end in a few numbers (e.g. "Output curve: 0.5
    # 1.2 2.4 4.8") would be classified as pure fluff and never translated.
    if fluff_match and len(fluff_match.group()) >= 0.8 * len(stripped):
        return False

    if not re.search(r"[A-Za-z]", stripped):
        return False

    return True
