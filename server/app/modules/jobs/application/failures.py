"""Stable, actionable projections of durable job failure codes."""

from __future__ import annotations

from app.modules.jobs.application.contracts import ActionableJobFailure

_INTEGRATION_FAILURES = frozenset(
    {"mineru_credential_required", "mineru_credential_invalid"}
)
_RETRYABLE_FAILURES = frozenset(
    {
        *_INTEGRATION_FAILURES,
        "mineru_rate_limited",
        "mineru_unavailable",
        "pdf_processing_timeout",
        "paper_ingestion_downloading_failed",
        "paper_ingestion_parsing_failed",
        "paper_ingestion_metadata_failed",
        "paper_ingestion_indexing_failed",
        "paper_ingestion_finalizing_failed",
        "document_reflow_failed",
    }
)


def actionable_job_failure(code: str | None) -> ActionableJobFailure | None:
    if not code:
        return None
    return ActionableJobFailure(
        code=code,
        retryable=code in _RETRYABLE_FAILURES,
        required_integration="mineru" if code in _INTEGRATION_FAILURES else None,
    )
