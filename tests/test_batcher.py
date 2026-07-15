from translator.batcher import make_batches
from translator.models import LineKind, RawLine


def _entry(key: str, value: str) -> RawLine:
    return RawLine(kind=LineKind.ENTRY, raw=f"{key}={value}", key=key, value=value)


def test_single_batch():
    entries = [_entry(f"k{i}", f"v{i}") for i in range(5)]
    batches = make_batches(entries, batch_size=10)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_multiple_batches():
    entries = [_entry(f"k{i}", f"v{i}") for i in range(10)]
    batches = make_batches(entries, batch_size=3)
    assert len(batches) == 4
    assert len(batches[0]) == 3
    assert len(batches[-1]) == 1


def test_empty():
    assert make_batches([], batch_size=50) == []


def test_char_budget_splits_batches():
    entries = [_entry(f"k{i}", "x" * 40) for i in range(10)]
    batches = make_batches(entries, batch_size=50, max_chars=100)
    assert len(batches) == 5
    assert all(len(b) == 2 for b in batches)


def test_oversized_entry_gets_own_batch():
    entries = [
        _entry("k0", "short"),
        _entry("k1", "y" * 500),
        _entry("k2", "short"),
    ]
    batches = make_batches(entries, batch_size=50, max_chars=100)
    assert [len(b) for b in batches] == [1, 1, 1]
