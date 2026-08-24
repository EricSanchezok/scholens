from __future__ import annotations

import pytest
from scholens_job_contracts import assess_pdf_text_candidate

from src.pdf.models import ParsedDocument, ParserBackend, ParserQuality
from src.pdf.quality import (
    UNICODE_REPLACEMENT_WARNING_CODE,
    apply_text_quality_policy,
    choose_local_candidate,
    replacement_character_count,
)


def _document(
    markdown: str,
    *,
    backend: ParserBackend = ParserBackend.PYMUPDF4LLM,
    quality: ParserQuality = ParserQuality.FULL,
    warning_code: str | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        markdown=markdown,
        page_offset_map={1: [0, len(markdown)]},
        backend=backend,
        quality=quality,
        parser_version="test",
        warning_code=warning_code,
    )


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


def test_quality_policy_preserves_contaminated_text_and_downgrades() -> None:
    source = _document("evidence \ufffd remains")

    result = apply_text_quality_policy(source)

    assert result.markdown == source.markdown
    assert result.quality is ParserQuality.TEXT_ONLY
    assert result.warning_code == UNICODE_REPLACEMENT_WARNING_CODE


def test_clean_fallback_wins_when_it_retains_content() -> None:
    evidence = "多语言 evidence about residual networks and attention. " * 40
    primary = _document(evidence + "damaged \ufffd equation")
    fallback = _document(
        evidence + "repaired λ equation",
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
        warning_code="markitdown_fallback",
    )

    assert choose_local_candidate(primary, fallback) is fallback


def test_short_clean_fallback_does_not_replace_substantive_primary() -> None:
    primary = _document(("complete paper evidence " * 100) + "\ufffd")
    fallback = _document(
        "one clean line",
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
    )

    assert choose_local_candidate(primary, fallback) is primary


def test_less_contaminated_fallback_wins_when_it_retains_content() -> None:
    evidence = "same substantive paper content about causal inference. " * 40
    primary = _document(evidence + "\ufffd\ufffd")
    fallback = _document(
        evidence + "\ufffd",
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
    )

    assert choose_local_candidate(primary, fallback) is fallback


def test_unrelated_equal_length_fallback_is_rejected() -> None:
    primary = _document(("vision transformer attention evidence " * 60) + "\ufffd")
    fallback = _document(
        "unrelated accounting ledger payroll material " * 60,
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
    )

    assert choose_local_candidate(primary, fallback) is primary


def test_repeated_oversized_fallback_is_rejected() -> None:
    evidence = "bounded evidence about graph neural networks. " * 60
    primary = _document(evidence + "\ufffd")
    fallback = _document(
        evidence * 2,
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
    )

    assert choose_local_candidate(primary, fallback) is primary


def test_whitespace_reflow_preserves_semantic_evidence() -> None:
    paragraph = "alpha beta gamma delta epsilon\n" * 100
    primary = _document(paragraph + "symbol \ufffd")
    fallback = _document(
        ("alpha  beta\ngamma delta epsilon " * 100) + "symbol λ",
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
    )

    assert choose_local_candidate(primary, fallback) is fallback


@pytest.mark.parametrize(
    ("current", "candidate"),
    [
        (("shared evidence " * 80) + "\ufffd", "shared evidence " * 80),
        (("shared evidence " * 80) + "\ufffd", "one unrelated line"),
        (("shared evidence " * 80) + "\ufffd", ("shared evidence " * 80) + "\ufffd"),
    ],
)
def test_jobs_candidate_adapter_matches_shared_contract(
    current: str,
    candidate: str,
) -> None:
    primary = _document(current)
    fallback = _document(candidate, backend=ParserBackend.MARKITDOWN)
    assessment = assess_pdf_text_candidate(current=current, candidate=candidate)

    assert (choose_local_candidate(primary, fallback) is fallback) is (
        assessment.safe_to_replace
    )
