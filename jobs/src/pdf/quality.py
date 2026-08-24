"""Jobs model adapter for the shared PDF text-quality contract."""

from __future__ import annotations

from dataclasses import replace

from scholens_job_contracts import (
    UNICODE_REPLACEMENT_WARNING_CODE,
    assess_pdf_text_candidate,
    replacement_character_count,
)

from src.pdf.models import ParsedDocument, ParserQuality


def apply_text_quality_policy(document: ParsedDocument) -> ParsedDocument:
    """Downgrade contaminated parser output while preserving the evidence."""
    if replacement_character_count(document.markdown) == 0:
        return document
    return replace(
        document,
        quality=ParserQuality.TEXT_ONLY,
        warning_code=UNICODE_REPLACEMENT_WARNING_CODE,
    )


def choose_local_candidate(
    primary: ParsedDocument,
    fallback: ParsedDocument,
) -> ParsedDocument:
    """Choose the least-corrupt local result without accepting severe text loss."""
    assessment = assess_pdf_text_candidate(
        current=primary.markdown,
        candidate=fallback.markdown,
    )
    return fallback if assessment.safe_to_replace else primary


__all__ = [
    "UNICODE_REPLACEMENT_WARNING_CODE",
    "apply_text_quality_policy",
    "choose_local_candidate",
    "replacement_character_count",
]
