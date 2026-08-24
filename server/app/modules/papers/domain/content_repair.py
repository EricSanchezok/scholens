"""Papers-domain adapter for the shared PDF text-quality contract."""

from __future__ import annotations

from scholens_job_contracts import (
    PDFTextCandidateAssessment,
    assess_pdf_text_candidate,
)


def assess_canonical_text_repair(
    *,
    current: str,
    candidate: str,
) -> PDFTextCandidateAssessment:
    """Assess a repair candidate while keeping Papers terminology local.

    A repair may only replace canonical text when it retains a conservative
    amount of content and sampled alphanumeric evidence. False negatives keep
    the readable current version, which is safer than accepting unrelated or
    severely truncated parser output.
    """
    return assess_pdf_text_candidate(current=current, candidate=candidate)


__all__ = [
    "assess_canonical_text_repair",
]
