"""Operation-specific research handlers behind the generic job callback."""

from __future__ import annotations

import uuid

from typing import Literal
from app.database.models import (
    JobOperation,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    ResearchAudienceType,
)
from app.shared.domain import AppError, FailureKind
from app.llm.token_credits import llm_usage_context, settle_token_usage
from app.modules.jobs.application.callbacks import (
    JobHandlerResult,
    JobPostCommitAction,
    ReleaseJobConcurrency,
    SettleJobUsage,
)
from app.modules.operation_journal.domain import OperationChange, ResourceRef
from app.modules.research.application.generation import (
    RESEARCH_AUDIO_OVERVIEW_CREATED,
    RESEARCH_DATA_TABLE_CREATED,
)
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.application.contracts import (
    AudioOverviewTaskPayload,
    AudioOverviewWebhookData,
    DataTableTaskPayload,
    DataTableWebhookData,
    JobClaimResponse,
    TokenUsageEventPayload,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session


def settle_jobs_usage(user_id: int, events: list[TokenUsageEventPayload]) -> None:
    for event in events:
        with llm_usage_context(
            user_id=user_id,
            feature=event.feature,
            operation_id=event.operation_id,
        ):
            settle_token_usage(
                provider=event.provider,
                model=event.model,
                ai_profile=event.ai_profile,
                thinking=event.thinking,
                thinking_effort=event.thinking_effort,
                profile_revision=event.profile_revision,
                provider_request_id=event.provider_request_id,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cache_hit_tokens=event.cache_hit_tokens,
                cache_miss_tokens=event.cache_miss_tokens,
                total_tokens=event.total_tokens,
                idempotency_key=event.idempotency_key,
                status=event.status,
            )


def _validate_callback(
    *,
    job_id: uuid.UUID,
    task_id: uuid.UUID,
    operation: str,
    expected_operation: JobOperation,
) -> None:
    if operation != expected_operation.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            kind=FailureKind.CONFLICT,
        )
    if task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback ID does not match",
            kind=FailureKind.CONFLICT,
        )


def _research_failure_result(
    *,
    db: Session,
    job_id: uuid.UUID,
    error_code: str,
    user_id: int | None,
    release_categories: tuple[Literal["audio", "background"], ...],
    usage_events: list[TokenUsageEventPayload],
) -> JobHandlerResult:
    """Mark a research callback job failed while still releasing its leases.

    A malformed payload or a missing result must not raise: raising skips the
    job-completion post-commit and leaks the audio/background concurrency
    leases for up to the TTL. Fail the job and release deterministically.
    """
    try:
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=error_code,
        )
    except AppError as exc:
        if exc.code != "job_not_found":
            raise
        changed = False
    post_commit: list[JobPostCommitAction] = []
    if user_id is not None:
        if usage_events:
            post_commit.append(
                SettleJobUsage(user_id=user_id, events=tuple(usage_events))
            )
        post_commit.extend(
            ReleaseJobConcurrency(user_id=user_id, category=category, job_id=job_id)
            for category in release_categories
        )
    return JobHandlerResult(
        value=JobClaimResponse(claimed=changed),
        post_commit=tuple(post_commit),
    )


async def complete_audio_job(
    job_id: uuid.UUID,
    webhook: AudioOverviewWebhookData,
    db: Session,
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    _validate_callback(
        job_id=job_id,
        task_id=webhook.task_id,
        operation=job.operation,
        expected_operation=JobOperation.AUDIO_GENERATE,
    )
    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "audio_generation_failed",
        )
    else:
        try:
            task_payload = AudioOverviewTaskPayload.model_validate(job.payload)
        except ValidationError:
            return _research_failure_result(
                db=db,
                job_id=job_id,
                error_code="audio_callback_payload_invalid",
                user_id=job.requested_by_id,
                release_categories=("audio", "background"),
                usage_events=webhook.usage_events,
            )
        result = webhook.result
        if result is None:
            return _research_failure_result(
                db=db,
                job_id=job_id,
                error_code="audio_callback_result_missing",
                user_id=job.requested_by_id,
                release_categories=("audio", "background"),
                usage_events=webhook.usage_events,
            )
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                kind=FailureKind.CONFLICT,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            scope_type = ResearchAudienceType(task_payload.scope_type)
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.AUDIO_OVERVIEW.value,
                created_by_id=job.requested_by_id,
                audience_type=scope_type.value,
                audience_document_id=(
                    task_payload.scope_id
                    if scope_type == ResearchAudienceType.DOCUMENT
                    else None
                ),
                audience_project_id=(
                    task_payload.scope_id
                    if scope_type == ResearchAudienceType.PROJECT
                    else None
                ),
                source_job_id=job_id,
            )
            item.audio_overview = ResearchAudioOverview(
                title=result.title,
                transcript=result.transcript,
                citations=result.citations,
                s3_object_key=result.s3_object_key,
                voice_id=result.voice_id,
                model_version=result.model_version,
            )
            db.add(item)
    changes = (
        (
            OperationChange(
                action=RESEARCH_AUDIO_OVERVIEW_CREATED,
                resources=(
                    ResourceRef("research_item", str(webhook.result.research_item_id)),
                ),
            ),
        )
        if changed and webhook.status == "completed" and webhook.result is not None
        else ()
    )
    post_commit = (
        (
            SettleJobUsage(
                user_id=job.requested_by_id,
                events=tuple(webhook.usage_events),
            ),
            ReleaseJobConcurrency(
                user_id=job.requested_by_id,
                category="audio",
                job_id=job_id,
            ),
            ReleaseJobConcurrency(
                user_id=job.requested_by_id,
                category="background",
                job_id=job_id,
            ),
        )
        if job.requested_by_id is not None
        else ()
    )
    return JobHandlerResult(
        value=JobClaimResponse(claimed=changed),
        changes=changes,
        post_commit=post_commit,
    )


async def complete_data_table_job(
    job_id: uuid.UUID,
    webhook: DataTableWebhookData,
    db: Session,
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    _validate_callback(
        job_id=job_id,
        task_id=webhook.task_id,
        operation=job.operation,
        expected_operation=JobOperation.DATA_TABLE_GENERATE,
    )
    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "data_table_processing_failed",
        )
    else:
        try:
            task_payload = DataTableTaskPayload.model_validate(job.payload)
        except ValidationError:
            return _research_failure_result(
                db=db,
                job_id=job_id,
                error_code="data_table_callback_payload_invalid",
                user_id=job.requested_by_id,
                release_categories=("background",),
                usage_events=webhook.usage_events,
            )
        result = webhook.result
        if result is None:
            return _research_failure_result(
                db=db,
                job_id=job_id,
                error_code="data_table_callback_result_missing",
                user_id=job.requested_by_id,
                release_categories=("background",),
                usage_events=webhook.usage_events,
            )
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                kind=FailureKind.CONFLICT,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.DATA_TABLE.value,
                created_by_id=job.requested_by_id,
                audience_type=ResearchAudienceType.PROJECT.value,
                audience_project_id=job.project_id,
                source_job_id=job_id,
            )
            item.data_table = ResearchDataTable(
                title=result.title,
                columns=result.columns,
                rows=[row.model_dump(mode="json") for row in result.rows],
                citations=[
                    citation.model_dump(mode="json")
                    for row in result.rows
                    for cell in row.values.values()
                    for citation in cell.citations
                ],
                row_failures=[str(document_id) for document_id in result.row_failures],
            )
            db.add(item)
    changes = (
        (
            OperationChange(
                action=RESEARCH_DATA_TABLE_CREATED,
                resources=(
                    ResourceRef("research_item", str(webhook.result.research_item_id)),
                ),
            ),
        )
        if changed and webhook.status == "completed" and webhook.result is not None
        else ()
    )
    post_commit = (
        (
            SettleJobUsage(
                user_id=job.requested_by_id,
                events=tuple(webhook.usage_events),
            ),
            ReleaseJobConcurrency(
                user_id=job.requested_by_id,
                category="background",
                job_id=job_id,
            ),
        )
        if job.requested_by_id is not None
        else ()
    )
    return JobHandlerResult(
        value=JobClaimResponse(claimed=changed),
        changes=changes,
        post_commit=post_commit,
    )
