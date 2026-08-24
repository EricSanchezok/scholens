from __future__ import annotations

import pytest

from scholens_job_contracts import (
    PDF_TEXT_MAX_CONTENT_RATIO,
    PDF_TEXT_MIN_CONTENT_RATIO,
    PDF_TEXT_MIN_EVIDENCE_COVERAGE,
    UNICODE_REPLACEMENT_CHARACTER,
    UNICODE_REPLACEMENT_WARNING_CODE,
    assess_pdf_text_candidate,
    replacement_character_count,
    retains_pdf_text_evidence,
)


def test_pdf_text_quality_public_constants_are_stable() -> None:
    assert UNICODE_REPLACEMENT_CHARACTER == "\ufffd"
    assert UNICODE_REPLACEMENT_WARNING_CODE == "unicode_replacement_detected"
    assert PDF_TEXT_MIN_CONTENT_RATIO == 0.8
    assert PDF_TEXT_MAX_CONTENT_RATIO == 1.25
    assert PDF_TEXT_MIN_EVIDENCE_COVERAGE == 0.8


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ordinary 中文 café 😀", 0),
        ("one \ufffd marker", 1),
        ("\ufffd two \ufffd markers", 2),
    ],
)
def test_replacement_character_count_is_exact(value: str, expected: int) -> None:
    assert replacement_character_count(value) == expected


def test_candidate_assessment_accepts_localized_unicode_recovery() -> None:
    paragraph = "多语言 evidence about convolutional networks and residual learning. "
    current = paragraph * 40 + "damaged \ufffd equation" + paragraph * 40
    candidate = paragraph * 40 + "repaired √ equation" + paragraph * 40

    assessment = assess_pdf_text_candidate(current=current, candidate=candidate)

    assert assessment.current_replacement_count == 1
    assert assessment.candidate_replacement_count == 0
    assert assessment.reduces_unicode_corruption
    assert assessment.retains_evidence
    assert assessment.safe_to_replace


def test_candidate_assessment_accepts_whitespace_reflow() -> None:
    current = ("alpha beta gamma delta epsilon\n" * 100) + "symbol \ufffd"
    candidate = ("alpha  beta\ngamma delta epsilon " * 100) + "symbol λ"

    assessment = assess_pdf_text_candidate(current=current, candidate=candidate)

    assert assessment.safe_to_replace


@pytest.mark.parametrize(
    "candidate",
    [
        "one clean line",
        "unrelated accounting ledger payroll material " * 100,
    ],
)
def test_candidate_assessment_rejects_missing_primary_evidence(
    candidate: str,
) -> None:
    current = ("vision transformer attention evidence " * 100) + "\ufffd"

    assessment = assess_pdf_text_candidate(current=current, candidate=candidate)

    assert assessment.reduces_unicode_corruption
    assert not assessment.retains_evidence
    assert not assessment.safe_to_replace


def test_candidate_assessment_rejects_oversized_repetition() -> None:
    evidence = "bounded evidence about graph neural networks. " * 60

    assessment = assess_pdf_text_candidate(
        current=evidence + "\ufffd",
        candidate=evidence * 2,
    )

    assert not assessment.safe_to_replace


def test_non_improving_candidate_skips_evidence_sampling() -> None:
    evidence = "same substantive paper content about causal inference. " * 40

    assessment = assess_pdf_text_candidate(
        current=evidence + "\ufffd",
        candidate=evidence + "\ufffd",
    )

    assert not assessment.reduces_unicode_corruption
    assert not assessment.retains_evidence
    assert not assessment.safe_to_replace


def test_evidence_check_is_independent_of_corruption_count() -> None:
    evidence = "shared paper evidence about multilingual retrieval. " * 40

    assert retains_pdf_text_evidence(current=evidence, candidate=evidence)


def test_candidate_assessment_rejects_reversed_paragraph_order() -> None:
    paragraphs = [
        (
            f"section {index} presents unique evidence token{index} "
            + f"and a distinct argument marker{index} " * 12
        )
        for index in range(100)
    ]
    current = "\n".join(paragraphs) + " damaged �"
    candidate = "\n".join(reversed(paragraphs)) + " repaired λ"

    assessment = assess_pdf_text_candidate(current=current, candidate=candidate)

    assert assessment.reduces_unicode_corruption
    assert not assessment.retains_evidence
    assert not assessment.safe_to_replace


def test_candidate_assessment_rejects_reversed_column_order() -> None:
    left_column = [
        f"left column finding {index} markerleft{index}" for index in range(80)
    ]
    right_column = [
        f"right column analysis {index} markerright{index}" for index in range(80)
    ]
    current = " ".join(left_column + right_column) + " �"
    candidate = " ".join(right_column + left_column) + " λ"

    assert not assess_pdf_text_candidate(
        current=current,
        candidate=candidate,
    ).safe_to_replace
