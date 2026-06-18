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
    r"|<[^>]+>)"  # <tag>
)


def _is_translatable(value: str) -> bool:
    if not value.strip():
        return False
    # strip all known variable tokens and whitespace
    stripped = _VAR_RE.sub("", value).strip()
    # if nothing left — pure variables, skip
    if not stripped:
        return False
    # if stripped has no letter characters at all
    if not re.search(r"[A-Za-z]", stripped):
        return False
    return True
