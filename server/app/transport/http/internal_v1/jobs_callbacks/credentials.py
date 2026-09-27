"""Signed, job-scoped just-in-time access to integration credentials."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    JobIntegrationCredentialResponse,
    JobExecutionScopeRequest,
    ZoteroJobCredentialResponse,
)
from app.shared.application import ApplicationExecutor
from app.transport.http.internal_v1.authentication import (
    verify_jobs_webhook,
    parse_callback_model,
)
from fastapi import APIRouter, Depends, Request

credentials_router = APIRouter()


@credentials_router.post(
    "/jobs/{job_id}/integration-credentials/mineru",
    response_model=JobIntegrationCredentialResponse,
)
def get_mineru_credential(
    job_id: UUID,
    request: Request,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobIntegrationCredentialResponse:
    scope = parse_callback_model(request, JobExecutionScopeRequest)

    def read(capabilities: ApplicationCapabilities) -> JobIntegrationCredentialResponse:
        capabilities.job_results.require_transport(
            job_id=job_id, generation=scope.claim_generation
        )
        return capabilities.job_mineru_credential(job_id=job_id)

    return executor.query(read)


@credentials_router.post(
    "/jobs/{job_id}/integration-credentials/zotero",
    response_model=ZoteroJobCredentialResponse,
)
def get_zotero_credential(
    job_id: UUID,
    request: Request,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroJobCredentialResponse:
    scope = parse_callback_model(request, JobExecutionScopeRequest)

    def read(capabilities: ApplicationCapabilities) -> ZoteroJobCredentialResponse:
        capabilities.job_results.require_transport(
            job_id=job_id, generation=scope.claim_generation
        )
        return capabilities.job_zotero_credential(job_id=job_id)

    return executor.query(read)


@credentials_router.post(
    "/jobs/{job_id}/integration-credentials/deepseek",
    response_model=JobIntegrationCredentialResponse,
)
def get_deepseek_credential(
    job_id: UUID,
    request: Request,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobIntegrationCredentialResponse:
    scope = parse_callback_model(request, JobExecutionScopeRequest)

    def read(capabilities: ApplicationCapabilities) -> JobIntegrationCredentialResponse:
        capabilities.job_results.require_transport(
            job_id=job_id, generation=scope.claim_generation
        )
        return capabilities.job_deepseek_credential(job_id=job_id)

    return executor.query(read)
