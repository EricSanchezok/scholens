from app.llm.utils import find_offsets


def test_find_offsets_returns_exact_span() -> None:
    assert find_offsets("paper", "read the paper today") == (9, 14)


def test_find_offsets_returns_missing_for_non_verbatim_quote() -> None:
    # The previous difflib longest-match fallback returned a partial 3-6
    # character window for paraphrased quotes, corrupting every highlight
    # built from it. Unmatched quotes must be reported as missing so callers
    # skip the annotation instead of persisting a broken anchor.
    assert find_offsets("paper result", "the paper finding") == (-1, -1)


def test_find_offsets_returns_missing_for_absent_quote() -> None:
    assert find_offsets("missing text", "unrelated content") == (-1, -1)


def test_find_offsets_handles_repeated_quotes() -> None:
    assert find_offsets("paper", "paper paper") == (0, 5)
