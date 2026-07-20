import json

import pytest

from translator.backends.base import BatchSizeMismatchError, ContextTooLongError
from translator.backends.lmstudio import _parse_json_response


def _array(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def test_parses_plain_array():
    assert _parse_json_response(_array(["Альфа", "Бета"]), expected_len=2) == [
        "Альфа",
        "Бета",
    ]


def test_trailing_empty_padding_is_dropped():
    # Observed with qwen3-14b: after a long entry the model appends a spurious
    # "" to the array. Retrying is useless at temperature 0, so drop the padding.
    output = _array(["Нейтрализовать корабли", "Длинный контракт...", ""])
    assert _parse_json_response(output, expected_len=2) == [
        "Нейтрализовать корабли",
        "Длинный контракт...",
    ]


def test_intentional_empty_translation_is_kept():
    assert _parse_json_response(_array(["Альфа", ""]), expected_len=2) == ["Альфа", ""]


def test_real_extra_entry_still_raises():
    output = _array(["Альфа", "Бета", "Гамма"])
    with pytest.raises(BatchSizeMismatchError):
        _parse_json_response(output, expected_len=2)


def test_missing_entry_raises():
    with pytest.raises(BatchSizeMismatchError):
        _parse_json_response(_array(["Альфа"]), expected_len=2)


def test_truncated_response_reports_context_overflow():
    with pytest.raises(ContextTooLongError):
        _parse_json_response('["Альфа", "Бет', expected_len=2)


def test_no_array_at_all_raises_value_error():
    with pytest.raises(ValueError, match="No JSON array"):
        _parse_json_response("I cannot translate this.", expected_len=1)
