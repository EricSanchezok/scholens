import pytest
from scholens_job_contracts import assess_pdf_text_candidate

from app.modules.papers.domain.content_repair import assess_canonical_text_repair


def test_canonical_text_repair_accepts_localized_unicode_recovery() -> None:
    paragraph = "多语言 evidence about convolutional networks and residual learning. "
    current = paragraph * 40 + "damaged \ufffd equation" + paragraph * 40
    candidate = paragraph * 40 + "repaired √ equation" + paragraph * 40

    assert assess_canonical_text_repair(
        current=current,
        candidate=candidate,
    ).safe_to_replace


def test_canonical_text_repair_accepts_whitespace_reflow() -> None:
    current = ("alpha beta gamma delta epsilon\n" * 100) + "symbol \ufffd"
    candidate = ("alpha  beta\ngamma delta epsilon " * 100) + "symbol λ"

    assert assess_canonical_text_repair(
        current=current,
        candidate=candidate,
    ).safe_to_replace


def test_canonical_text_repair_rejects_severely_truncated_clean_candidate() -> None:
    current = ("complete paper evidence " * 200) + "\ufffd"

    assert not assess_canonical_text_repair(
        current=current,
        candidate="one clean line",
    ).safe_to_replace


def test_canonical_text_repair_rejects_unrelated_equal_length_candidate() -> None:
    current = ("vision transformer attention evidence " * 100) + "\ufffd"
    candidate = "unrelated accounting ledger payroll material " * 100

    assert not assess_canonical_text_repair(
        current=current,
        candidate=candidate,
    ).safe_to_replace


@pytest.mark.parametrize(
    ("current", "candidate"),
    [
        (("shared evidence " * 80) + "\ufffd", "shared evidence " * 80),
        (("shared evidence " * 80) + "\ufffd", "one unrelated line"),
        (("shared evidence " * 80) + "\ufffd", ("shared evidence " * 80) + "\ufffd"),
    ],
)
def test_server_repair_adapter_matches_shared_contract(
    current: str,
    candidate: str,
) -> None:
    assert assess_canonical_text_repair(
        current=current,
        candidate=candidate,
    ) == assess_pdf_text_candidate(current=current, candidate=candidate)
