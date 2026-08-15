"""Signed, job-scoped just-in-time access to integration credentials."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import JobIntegrationCredentialResponse
from app.shared.application import ApplicationExecutor
from app.transport.http.internal_v1.authentication import verify_jobs_webhook
from fastapi import APIRouter, Depends

credentials_router = APIRouter()


@credentials_router.post(
    "/jobs/{job_id}/integration-credentials/mineru",
    response_model=JobIntegrationCredentialResponse,
)
def get_mineru_credential(
    job_id: UUID,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobIntegrationCredentialResponse:
    return executor.query(
        lambda capabilities: capabilities.job_mineru_credential(job_id=job_id)
    )
