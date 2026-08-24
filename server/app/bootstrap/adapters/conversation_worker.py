"""Composition adapter for the durable Server-owned Conversation worker task."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from celery import Task
from pydantic import BaseModel, ConfigDict
from redis import Redis
from redis.exceptions import RedisError
from scholens_observability import (
    add_counter,
    bind_context,
    build_snapshot,
    log_event,
    record_histogram,
)

from app.database.database import SessionLocal
from app.bootstrap.adapters.conversation_job_recovery import (
    fail_interrupted_conversation_response,
)
from app.modules.conversations.infrastructure.celery_app import celery_app
from app.modules.conversations.infrastructure.event_store import ConversationEventStore
from app.modules.conversations.infrastructure.models import ConversationResponse
from app.modules.conversations.infrastructure.worker_runtime import (
    ConversationWorkerRuntime,
    create_conversation_worker_runtime,
)
from app.modules.identity.infrastructure.users import (
    actor_from_auth_user,
    user_repository,
)
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.infrastructure.models import DurableJob
from app.shared.application import (
    Actor,
    JobOrigin,
    OperationContext,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobStatus

logger = logging.getLogger(__name__)


class ConversationGenerationTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    turn_id: UUID
    response_id: UUID
    generation_kind: Literal["initial", "retry", "branch"]


@dataclass(frozen=True, slots=True)
class ClaimedGeneration:
    actor: Actor
    correlation_id: UUID
    origin_operation_id: UUID


_worker_runtime: ConversationWorkerRuntime | None = None


def _runtime() -> ConversationWorkerRuntime:
    global _worker_runtime
    if _worker_runtime is None:
        _worker_runtime = create_conversation_worker_runtime()
    return _worker_runtime


def _release_concurrency(*, user_id: int, response_id: UUID) -> None:
    redis_url = _runtime().settings.resolved_cache_url
    if redis_url is None:
        return
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    try:
        client.zrem(
            f"scholens:concurrency:interactive:{user_id}",
            str(response_id),
        )
    except RedisError:
        logger.warning(
            "conversation.concurrency_release.failed",
            exc_info=True,
            extra={"response_id": str(response_id)},
        )
    finally:
        client.close()


def _record_claim_age(
    job: DurableJob,
    *,
    generation_kind: Literal["initial", "retry", "branch"],
) -> None:
    if not isinstance(job.created_at, datetime):
        return
    record_histogram(
        "scholens.conversation.worker.claim_age",
        max(0, (datetime.now(UTC) - job.created_at).total_seconds()),
        unit="s",
        attributes={"generation_kind": generation_kind},
    )


def _claim(request: ConversationGenerationTaskRequest) -> ClaimedGeneration | None:
    release_user_id: int | None = None
    claimed: ClaimedGeneration | None = None
    with SessionLocal.begin() as db:
        job: DurableJob | None = None
        interrupted = job_repository.interrupt_expired_conversation(
            db,
            job_id=request.response_id,
        )
        if interrupted is not None:
            fail_interrupted_conversation_response(db, interrupted)
            release_user_id = interrupted.requested_by_id
        else:
            job = job_repository.claim(
                db,
                job_id=request.response_id,
                recover_expired=False,
            )
            if job is None:
                existing = db.get(DurableJob, request.response_id)
                if (
                    existing is not None
                    and existing.requested_by_id is not None
                    and JobStatus(existing.status)
                    in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
                ):
                    release_user_id = existing.requested_by_id
            else:
                _record_claim_age(job, generation_kind=request.generation_kind)
                if job.requested_by_id is None:
                    response = db.get(ConversationResponse, request.response_id)
                    if response is not None and response.status == "running":
                        response.status = "failed"
                        response.failure = {
                            "code": "conversation_actor_unavailable",
                            "kind": FailureKind.UNAVAILABLE.value,
                            "retryable": False,
                            "correlation_id": str(job.correlation_id),
                        }
                        response.turn.selected_response_id = response.id
                    job_repository.fail(
                        db,
                        job_id=request.response_id,
                        error_code="conversation_actor_unavailable",
                    )
                else:
                    user = user_repository.get(db, id=job.requested_by_id)
                    if user is not None:
                        claimed = ClaimedGeneration(
                            actor=actor_from_auth_user(user),
                            correlation_id=job.correlation_id,
                            origin_operation_id=job.origin_operation_id,
                        )
                    else:
                        response = db.get(ConversationResponse, request.response_id)
                        if response is not None and response.status == "running":
                            response.status = "failed"
                            response.failure = {
                                "code": "conversation_actor_unavailable",
                                "kind": FailureKind.UNAVAILABLE.value,
                                "retryable": False,
                                "correlation_id": str(job.correlation_id),
                            }
                            response.turn.selected_response_id = response.id
                        release_user_id = job.requested_by_id
                        job_repository.fail(
                            db,
                            job_id=request.response_id,
                            error_code="conversation_actor_unavailable",
                        )
    if release_user_id is not None:
        _release_concurrency(
            user_id=release_user_id,
            response_id=request.response_id,
        )
    return claimed


def _heartbeat_and_status(response_id: UUID) -> str | None:
    with SessionLocal.begin() as db:
        response = db.get(ConversationResponse, response_id)
        if response is None:
            return None
        job_repository.heartbeat(db, job_id=response_id)
        status = response.status
        return status


def _terminal_status(response_id: UUID) -> tuple[str | None, str | None]:
    with SessionLocal() as db:
        response = db.get(ConversationResponse, response_id)
        if response is None:
            return None, None
        failure_code = None
        if response.failure is not None:
            value = response.failure.get("code")
            failure_code = value if isinstance(value, str) else None
        return response.status, failure_code


def _complete_job(response_id: UUID) -> None:
    with SessionLocal.begin() as db:
        job_repository.complete(
            db,
            job_id=response_id,
            result={"response_id": str(response_id)},
        )


def _fail_job(response_id: UUID, *, error_code: str) -> None:
    with SessionLocal.begin() as db:
        job_repository.fail(db, job_id=response_id, error_code=error_code)


def _persist_unhandled_failure(
    request: ConversationGenerationTaskRequest,
    claimed: ClaimedGeneration,
    error: BaseException,
) -> UUID:
    snapshot_id = uuid4()
    app_error = (
        error
        if isinstance(error, AppError)
        else AppError(
            code="generation_interrupted",
            message="Conversation generation was interrupted.",
            kind=FailureKind.UNAVAILABLE,
            retryable=True,
        )
    )
    with SessionLocal.begin() as db:
        response = db.get(ConversationResponse, request.response_id)
        if response is not None and response.status == "running":
            response.status = "failed"
            response.failure = {
                "code": app_error.code,
                "kind": app_error.kind.value,
                "retryable": app_error.retryable,
                "diagnostic_id": str(snapshot_id),
                "correlation_id": str(claimed.correlation_id),
            }
            response.turn.selected_response_id = response.id
        job_repository.fail(
            db,
            job_id=request.response_id,
            error_code=app_error.code,
        )
    return snapshot_id


async def _monitor(response_id: UUID, generation: asyncio.Task[None]) -> None:
    while not generation.done():
        await asyncio.sleep(1)
        status = await asyncio.to_thread(_heartbeat_and_status, response_id)
        if status == "cancelled":
            generation.cancel()
            return


async def _run_generation(
    request: ConversationGenerationTaskRequest,
    claimed: ClaimedGeneration,
) -> None:
    runtime = _runtime()
    operation_factory = runtime.operation_factory
    operation: OperationContext = operation_factory.resume(
        correlation_id=claimed.correlation_id,
        causation_id=claimed.origin_operation_id,
        initiated_by=OperationInitiator.SYSTEM,
        origin=JobOrigin(
            job_id=request.response_id,
            delivery_ref=None,
            request_id=None,
        ),
        credential=None,
    )
    with bind_context(
        service="scholens-conversation-worker",
        environment=runtime.settings.environment,
        release=runtime.settings.release_sha,
        operation_id=str(operation.trace.operation_id),
        correlation_id=str(operation.trace.correlation_id),
        causation_id=str(operation.trace.causation_id),
        actor_id=str(claimed.actor.id),
        origin=operation.origin.kind,
        component="conversation_generation",
        stage="conversation_stream",
        conversation_id=str(request.conversation_id),
        turn_id=str(request.turn_id),
        job_id=str(request.response_id),
    ):
        source = await runtime.chat.resume(
            actor=claimed.actor,
            operation=operation,
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            generation_kind=request.generation_kind,
        )
        store = ConversationEventStore(runtime.settings.resolved_cache_url)

        async def drain() -> None:
            async for _frame in store.publish(
                response_id=request.response_id,
                source=source,
            ):
                pass

        generation = asyncio.create_task(
            drain(),
            name=f"conversation-generation:{request.response_id}",
        )
        monitor = asyncio.create_task(
            _monitor(request.response_id, generation),
            name=f"conversation-generation-monitor:{request.response_id}",
        )
        try:
            await generation
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


def generate_conversation_response(
    self: Task,
    *,
    request: dict[str, object],
) -> None:
    del self
    parsed = ConversationGenerationTaskRequest.model_validate(request)
    claimed = _claim(parsed)
    if claimed is None:
        return
    add_counter(
        "scholens.conversation.generations",
        attributes={"status": "started", "kind": parsed.generation_kind},
    )
    try:
        asyncio.run(_run_generation(parsed, claimed))
    except asyncio.CancelledError:
        add_counter(
            "scholens.conversation.generations",
            attributes={"status": "cancelled", "kind": parsed.generation_kind},
        )
    except BaseException as error:
        snapshot_id = _persist_unhandled_failure(parsed, claimed, error)
        runtime = _runtime()
        try:
            runtime.diagnostic_recorder.record(
                build_snapshot(
                    snapshot_id=snapshot_id,
                    service="scholens-conversation-worker",
                    environment=runtime.settings.environment,
                    release=runtime.settings.release_sha,
                    reason="conversation_generation_interrupted",
                    request_id=None,
                    operation_id=str(parsed.response_id),
                    correlation_id=str(claimed.correlation_id),
                    actor_id=str(claimed.actor.id),
                    sections={
                        "failure": {
                            "code": (
                                error.code
                                if isinstance(error, AppError)
                                else "generation_interrupted"
                            ),
                            "exception_type": type(error).__name__,
                        },
                        "conversation": {
                            "conversation_id": str(parsed.conversation_id),
                            "turn_id": str(parsed.turn_id),
                            "response_id": str(parsed.response_id),
                            "generation_kind": parsed.generation_kind,
                        },
                    },
                )
            )
        except Exception as diagnostic_error:
            log_event(
                logger,
                logging.ERROR,
                "diagnostic.snapshot.capture_failed",
                exc_info=diagnostic_error,
                diagnostic_id=str(snapshot_id),
            )
        log_event(
            logger,
            logging.ERROR,
            "conversation.generation.interrupted",
            exc_info=error,
            response_id=str(parsed.response_id),
            diagnostic_id=str(snapshot_id),
        )
        add_counter(
            "scholens.conversation.generations",
            attributes={"status": "failed", "kind": parsed.generation_kind},
        )
    else:
        status, failure_code = _terminal_status(parsed.response_id)
        if status == "completed":
            _complete_job(parsed.response_id)
            metric_status = "completed"
        elif status == "failed":
            _fail_job(
                parsed.response_id,
                error_code=failure_code or "conversation_generation_failed",
            )
            metric_status = "failed"
        else:
            metric_status = status or "missing"
        add_counter(
            "scholens.conversation.generations",
            attributes={"status": metric_status, "kind": parsed.generation_kind},
        )
    finally:
        _release_concurrency(
            user_id=claimed.actor.id,
            response_id=parsed.response_id,
        )


generate_conversation_response = cast(
    Callable[..., None],
    celery_app.task(
        bind=True,
        name=(
            "app.bootstrap.adapters.conversation_worker.generate_conversation_response"
        ),
    )(generate_conversation_response),
)


__all__ = ["generate_conversation_response"]
