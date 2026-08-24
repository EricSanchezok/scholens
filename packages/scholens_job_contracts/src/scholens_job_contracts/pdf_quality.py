"""Service-neutral quality contract for extracted PDF text candidates."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

UNICODE_REPLACEMENT_CHARACTER = "\ufffd"
UNICODE_REPLACEMENT_WARNING_CODE = "unicode_replacement_detected"

PDF_TEXT_MIN_CONTENT_RATIO = 0.8
PDF_TEXT_MAX_CONTENT_RATIO = 1.25
PDF_TEXT_MIN_EVIDENCE_COVERAGE = 0.8

_EVIDENCE_WINDOW_CHARACTERS = 32
_MAX_EVIDENCE_WINDOWS = 64


@dataclass(frozen=True, slots=True)
class PDFTextCandidateAssessment:
    """Deterministic evidence for accepting or rejecting one candidate."""

    current_replacement_count: int
    candidate_replacement_count: int
    retains_evidence: bool

    @property
    def reduces_unicode_corruption(self) -> bool:
        return self.candidate_replacement_count < self.current_replacement_count

    @property
    def safe_to_replace(self) -> bool:
        return self.reduces_unicode_corruption and self.retains_evidence


def replacement_character_count(value: str) -> int:
    """Count explicit Unicode replacement characters without rewriting text."""
    return value.count(UNICODE_REPLACEMENT_CHARACTER)


def _substantive_character_count(value: str) -> int:
    return sum(
        character != UNICODE_REPLACEMENT_CHARACTER and not character.isspace()
        for character in value
    )


def _semantic_evidence(value: str) -> str:
    """Normalize formatting away while retaining lexical evidence."""
    return "".join(character for character in value.casefold() if character.isalnum())


def _evidence_windows(value: str) -> Iterator[str]:
    window_characters = min(
        _EVIDENCE_WINDOW_CHARACTERS,
        max(8, len(value) // 8),
    )
    if len(value) <= window_characters:
        if value:
            yield value
        return
    available = len(value) - window_characters
    count = min(_MAX_EVIDENCE_WINDOWS, available + 1)
    positions = {round(index * available / (count - 1)) for index in range(count)}
    for position in sorted(positions):
        yield value[position : position + window_characters]


def retains_pdf_text_evidence(*, current: str, candidate: str) -> bool:
    """Return whether a candidate conservatively represents the same text."""
    current_size = _substantive_character_count(current)
    candidate_size = _substantive_character_count(candidate)
    if current_size == 0 or candidate_size == 0:
        return False
    content_ratio = candidate_size / current_size
    if not PDF_TEXT_MIN_CONTENT_RATIO <= content_ratio <= PDF_TEXT_MAX_CONTENT_RATIO:
        return False

    current_evidence = _semantic_evidence(current)
    candidate_evidence = _semantic_evidence(candidate)
    windows = tuple(_evidence_windows(current_evidence))
    if not windows:
        return False
    # Presence alone is insufficient: a fallback parser can retain every word
    # while reversing columns or paragraphs. Match sampled evidence in source
    # order, advancing one character so overlapping windows remain valid.
    matched = 0
    search_from = 0
    for window in windows:
        position = candidate_evidence.find(window, search_from)
        if position < 0:
            continue
        matched += 1
        search_from = position + 1
    return matched / len(windows) >= PDF_TEXT_MIN_EVIDENCE_COVERAGE


def assess_pdf_text_candidate(
    *,
    current: str,
    candidate: str,
) -> PDFTextCandidateAssessment:
    """Assess whether a less-corrupt candidate retains the current evidence."""
    current_replacement_count = replacement_character_count(current)
    candidate_replacement_count = replacement_character_count(candidate)
    reduces_unicode_corruption = candidate_replacement_count < current_replacement_count
    return PDFTextCandidateAssessment(
        current_replacement_count=current_replacement_count,
        candidate_replacement_count=candidate_replacement_count,
        retains_evidence=(
            retains_pdf_text_evidence(current=current, candidate=candidate)
            if reduces_unicode_corruption
            else False
        ),
    )


__all__ = [
    "PDF_TEXT_MAX_CONTENT_RATIO",
    "PDF_TEXT_MIN_CONTENT_RATIO",
    "PDF_TEXT_MIN_EVIDENCE_COVERAGE",
    "PDFTextCandidateAssessment",
    "UNICODE_REPLACEMENT_CHARACTER",
    "UNICODE_REPLACEMENT_WARNING_CODE",
    "assess_pdf_text_candidate",
    "replacement_character_count",
    "retains_pdf_text_evidence",
]
