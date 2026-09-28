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

PDF_SOURCE_FAILURE_CODES = {
    "invalid_pdf": "invalid_pdf",
    "upload_too_large": "upload_too_large",
    "source_checksum_mismatch": "invalid_pdf",
    "paper_source_unsafe_address": "paper_source_unsafe_address",
    "paper_source_pdf_unavailable": "paper_source_pdf_unavailable",
    "paper_source_http_error": "paper_source_pdf_unavailable",
    "paper_source_redirect_invalid": "paper_source_pdf_unavailable",
    "paper_source_content_length_invalid": "paper_source_pdf_unavailable",
    "paper_source_resolution_failed": "paper_source_pdf_unavailable",
    "paper_source_resolution_unavailable": "paper_ingestion_downloading_failed",
    "paper_source_resolution_invalid": "paper_ingestion_downloading_failed",
    "paper_source_dns_failed": "paper_ingestion_downloading_failed",
    "paper_source_timeout": "paper_ingestion_downloading_failed",
    "paper_source_network_error": "paper_ingestion_downloading_failed",
    "paper_source_retryable": "paper_ingestion_downloading_failed",
    "paper_source_materialization_failed": "paper_ingestion_downloading_failed",
    "source_ready_unavailable": "paper_ingestion_claim_failed",
}

SAFE_PDF_FAILURE_CODES = frozenset(
    {
        *PDF_SOURCE_FAILURE_CODES.values(),
        "pdf_content_insufficient",
        "job_execution_retry_exhausted",
        "provider_outcome_unknown",
        "job_owner_unavailable",
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
    if reason in PDF_SOURCE_FAILURE_CODES:
        return PDF_SOURCE_FAILURE_CODES[reason]
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
    compact: bool = False,
) -> bool:
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result=(
            result.model_dump(
                mode="json",
                exclude={"raw_content", "page_offset_map", "metadata"}
                if compact
                else None,
            )
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
