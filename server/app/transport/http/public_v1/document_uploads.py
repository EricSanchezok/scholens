"""HTTP adapter for the shared PDF-ingestion application capability."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.bootstrap.execution import get_paper_ingestion_workflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.contracts.uploads import PaperIngestionRequest
from app.modules.papers.application.upload_sessions import (
    PreparePaperUploadRequest,
    PreparePaperUploadResponse,
)
from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.client_ip import http_client_ip
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Header, Request, Response

document_upload_router = APIRouter()

IdempotencyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]


@document_upload_router.post(
    "/sources",
    response_model=LibraryPaperIngestionResponse,
    status_code=202,
)
async def upload_pdf_from_source(
    payload: PaperIngestionRequest,
    request: Request,
    idempotency_key: IdempotencyHeader = None,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    ingestion: PaperIngestionWorkflow = Depends(get_paper_ingestion_workflow),
) -> LibraryPaperIngestionResponse:
    if payload.source.kind == "upload":
        return await ingestion.from_upload_session(
            actor=current_user,
            operation=operation,
            upload_id=payload.source.upload_id,
            project_id=payload.project_id,
            add_to_library=payload.add_to_library,
            idempotency_key=idempotency_key,
            ip_address=http_client_ip(request),
        )
    value = (
        payload.source.doi
        if payload.source.kind == "doi"
        else (
            payload.source.arxiv_id
            if payload.source.kind == "arxiv"
            else payload.source.url
        )
    )
    return await ingestion.from_source(
        actor=current_user,
        operation=operation,
        kind=payload.source.kind,
        value=value,
        project_id=payload.project_id,
        add_to_library=payload.add_to_library,
        idempotency_key=idempotency_key,
        ip_address=http_client_ip(request),
    )


@document_upload_router.post(
    "/uploads",
    response_model=PreparePaperUploadResponse,
    status_code=201,
)
def prepare_pdf_upload(
    payload: PreparePaperUploadRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> PreparePaperUploadResponse:
    return executor.command(
        lambda capabilities: capabilities.paper_uploads.prepare(
            actor=current_user,
            request=payload,
        )
    )


@document_upload_router.post(
    "/{job_id}/retries",
    response_model=LibraryPaperIngestionResponse,
    status_code=202,
)
async def retry_pdf_ingestion(
    job_id: UUID,
    idempotency_key: IdempotencyHeader = None,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    ingestion: PaperIngestionWorkflow = Depends(get_paper_ingestion_workflow),
) -> LibraryPaperIngestionResponse:
    return await ingestion.retry(
        actor=current_user,
        operation=operation,
        job_id=job_id,
        idempotency_key=idempotency_key,
    )


@document_upload_router.delete("/{job_id}", status_code=204)
async def cancel_pdf_ingestion(
    job_id: UUID,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    ingestion: PaperIngestionWorkflow = Depends(get_paper_ingestion_workflow),
) -> Response:
    await ingestion.cancel(
        actor=current_user,
        operation=operation,
        job_id=job_id,
    )
    return Response(status_code=204)
