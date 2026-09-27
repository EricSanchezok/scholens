"""Metadata-only, signed execution and result-inbox transport."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from scholens_job_contracts import (
    JobExecutionClaim,
    JobResultManifest,
    JobResultReceipt,
)

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    ClaimExecutionRequest,
    ExecutionProgressRequest,
)
from app.shared.application import ApplicationExecutor
from app.transport.http.internal_v1.authentication import (
    parse_callback_model,
    verify_jobs_webhook,
)

result_router = APIRouter()


@result_router.post("/jobs/{job_id}/execution/claim", response_model=JobExecutionClaim)
def claim_execution(
    job_id: UUID,
    request: Request,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobExecutionClaim:
    payload = parse_callback_model(request, ClaimExecutionRequest)
    return executor.command(
        lambda capabilities: capabilities.job_results.claim(
            job_id=job_id, claim_token=payload.claim_token
        )
    )


@result_router.post(
    "/jobs/{job_id}/execution/progress", response_model=JobExecutionClaim
)
def progress_execution(
    job_id: UUID,
    request: Request,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobExecutionClaim:
    payload = parse_callback_model(request, ExecutionProgressRequest)
    return executor.command(
        lambda capabilities: capabilities.job_results.heartbeat(
            job_id=job_id,
            generation=payload.claim_generation,
            progress_code=payload.progress.progress_code if payload.progress else None,
        )
    )


@result_router.post("/jobs/{job_id}/results", response_model=JobResultReceipt)
def accept_result(
    job_id: UUID,
    request: Request,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobResultReceipt:
    manifest = parse_callback_model(request, JobResultManifest)
    return executor.command(
        lambda capabilities: capabilities.job_results.accept(
            job_id=job_id,
            manifest=manifest,
            request_id=verified.request_id,
            delivery_ref=verified.delivery_ref,
        )
    )
