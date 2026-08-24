"""Small primitives shared by PDF callback adapters."""

import uuid

from sqlalchemy.orm import Session

from app.modules.jobs.application.contracts import PDFProcessingResult
from app.modules.jobs.infrastructure.repository import job_repository
from app.shared.domain import JsonValue
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)

SAFE_PDF_FAILURE_CODES = frozenset(
    {
        "pdf_content_insufficient",
        "pdf_processing_timeout",
        "mineru_credential_required",
        "mineru_credential_invalid",
        "mineru_rate_limited",
        "mineru_unavailable",
        "mineru_content_insufficient",
        "mineru_response_unsafe",
        "job_result_key_mismatch",
        "paper_ingestion_downloading_failed",
        "paper_ingestion_parsing_failed",
        "paper_ingestion_metadata_failed",
        "paper_ingestion_indexing_failed",
        "paper_ingestion_finalizing_failed",
        "jobs_callback_too_large",
        "jobs_callback_invalid",
        "paper_ingestion_claim_failed",
    }
)
PDF_PROGRESS_FAILURE_CODES = {
    "downloading": "paper_ingestion_downloading_failed",
    "parsing": "paper_ingestion_parsing_failed",
    "extracting_metadata": "paper_ingestion_metadata_failed",
    "indexing": "paper_ingestion_indexing_failed",
    "finalizing": "paper_ingestion_finalizing_failed",
}


def safe_pdf_failure_code(*, reason: str, progress_code: str | None) -> str:
    if reason in SAFE_PDF_FAILURE_CODES:
        return reason
    if progress_code is None:
        return "paper_ingestion_parsing_failed"
    return PDF_PROGRESS_FAILURE_CODES.get(
        progress_code,
        "paper_ingestion_parsing_failed",
    )


def complete_pdf_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    result: PDFProcessingResult,
    persisted_result: dict[str, JsonValue] | None = None,
) -> bool:
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result=(
            result.model_dump(mode="json")
            if persisted_result is None
            else persisted_result
        ),
    )
    return changed


def document_change(
    *,
    action: OperationAction,
    document_id: object,
) -> OperationChange:
    return OperationChange(
        action=action,
        resources=(ResourceRef("document", str(document_id)),),
    )
