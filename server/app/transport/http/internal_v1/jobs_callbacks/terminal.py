"""Generic terminal callback surface for every durable Jobs operation."""

import uuid
from typing import Annotated

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.bootstrap.execution import get_job_completion_processor
from app.bootstrap.execution import get_operation_context_factory
from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
    SourceReadyCallback,
    JobSourceUrlResponse,
)
from app.shared.application import (
    ApplicationExecutor,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.transport.http.internal_v1.authentication import verify_jobs_webhook
from app.transport.http.internal_v1.authentication import (
    parse_callback_model,
    parse_callback_object,
)
from fastapi import APIRouter, Depends, Query, Request

terminal_router = APIRouter()


@terminal_router.post(
    "/jobs/{job_id}/source-url",
    response_model=JobSourceUrlResponse,
)
async def resolve_source_url(
    job_id: uuid.UUID,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> JobSourceUrlResponse:
    return await processor.resolve_source_url(job_id=job_id, verified=verified)


@terminal_router.post("/jobs/{job_id}/source-ready")
def source_ready_job(
    job_id: uuid.UUID,
    request: Request,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> object:
    return processor.source_ready(
        job_id=job_id,
        callback=parse_callback_model(request, SourceReadyCallback),
        verified=verified,
    )


@terminal_router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    request: Request,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> object:
    return await processor.complete(
        job_id=job_id,
        payload=parse_callback_object(request),
        verified=verified,
    )


@terminal_router.post(
    "/jobs/{job_id}/fail",
    response_model=JobClaimResponse,
)
def fail_job(
    job_id: uuid.UUID,
    request: Request,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> JobClaimResponse:
    return processor.fail(
        job_id=job_id,
        callback=parse_callback_model(request, JobFailureCallback),
        verified=verified,
    )


@terminal_router.post("/schedules/zotero-sync")
def schedule_zotero_sync(
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    threshold_seconds: int = Query(default=24 * 3600),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> dict[str, int]:
    operation = operation_factory.root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin(
            task_name="zotero_sync",
            run_id=verified.request_id,
        ),
        credential=None,
    )
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.schedule_zotero_sync(
            operation=operation, threshold_seconds=threshold_seconds
        )
    )


@terminal_router.post("/schedules/reading-activity-retention")
def purge_reading_activity_detail(
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    batch_size: int = Query(default=100, ge=1, le=100),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> dict[str, int | str]:
    """Apply one hourly, bounded page-detail retention batch."""

    operation = operation_factory.root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin(
            task_name="reading_activity_retention",
            run_id=verified.request_id,
        ),
        credential=None,
    )
    result = executor.command(
        lambda capabilities: (
            capabilities.reading_activity_retention.purge_scheduled_session_pages(
                operation=operation,
                batch_size=batch_size,
            )
        )
    )
    return {
        "cutoff": result.cutoff.isoformat(),
        "candidates": result.candidates,
        "purged_sessions": result.purged_sessions,
        "purged_pages": result.purged_pages,
        "remaining_candidates": max(
            0,
            result.candidates - result.purged_sessions,
        ),
    }
