"""Recoverable transactional-outbox publisher for Jobs tasks."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

from app.database.database import SessionLocal
from app.modules.jobs.infrastructure.client import jobs_client
from app.modules.jobs.infrastructure.repository import (
    ReservedJobDispatch,
    job_repository,
)
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.jobs.infrastructure.dispatcher_wakeup import JobDispatcherWakeup
from sqlalchemy.orm import Session
from scholens_observability import add_counter, instrumented_span, record_histogram

logger = logging.getLogger(__name__)

DISPATCH_BATCH_SIZE = 20
DISPATCH_IDLE_SECONDS = float(os.getenv("JOB_DISPATCH_INTERVAL_SECONDS", "1"))
MAX_BACKOFF_SECONDS = 60
PUBLISH_LEASE = timedelta(
    seconds=float(os.getenv("JOB_DISPATCH_PUBLISH_LEASE_SECONDS", "30"))
)
UNCLAIMED_PDF_MAX_AGE = timedelta(
    seconds=float(os.getenv("JOB_UNCLAIMED_TIMEOUT_SECONDS", "3600"))
)
if UNCLAIMED_PDF_MAX_AGE <= timedelta(0):
    raise RuntimeError("JOB_UNCLAIMED_TIMEOUT_SECONDS must be positive")


def _reserve_dispatches(
    *,
    limit: int,
    recover_conversation: Callable[[Session, DurableJob], None] | None,
    recover_unclaimed_pdf: Callable[[Session, DurableJob], None] | None,
) -> tuple[ReservedJobDispatch, ...]:
    """Lease a batch in one short progress transaction."""
    recovered_count = 0
    recovered_pdf_count = 0
    with SessionLocal() as db:
        recovered_count = job_repository.recover_expired_leases(
            db,
            limit=limit,
            recover_conversation=recover_conversation,
        )
        if recover_unclaimed_pdf is not None:
            try:
                recovered_pdf_count = job_repository.recover_stale_unclaimed_pdf_jobs(
                    db,
                    limit=limit,
                    max_age=UNCLAIMED_PDF_MAX_AGE,
                    recover_pdf=recover_unclaimed_pdf,
                )
            except Exception:
                # Entering this fallback path is itself unhealthy. Preserve
                # that signal even when the recovery transaction rolls back.
                add_counter("scholens.jobs.pdf_unclaimed_recoveries")
                raise
        dispatches = job_repository.reserve_dispatches(
            db,
            limit=limit,
            lease=PUBLISH_LEASE,
        )
        db.commit()
    if recovered_count:
        logger.warning(
            "jobs.leases.recovered",
            extra={"recovered_count": recovered_count},
        )
    if recovered_pdf_count:
        add_counter(
            "scholens.jobs.pdf_unclaimed_recoveries",
            value=recovered_pdf_count,
        )
        logger.error(
            "jobs.pdf_unclaimed.recovered",
            extra={"recovered_count": recovered_pdf_count},
        )
    return dispatches


def _record_publish_success(dispatch: ReservedJobDispatch) -> bool:
    with SessionLocal() as db:
        changed = job_repository.complete_dispatch(
            db,
            dispatch_id=dispatch.dispatch_id,
            attempt_count=dispatch.attempt_count,
        )
        db.commit()
    return changed


def _record_publish_failure(
    dispatch: ReservedJobDispatch,
    *,
    error: RuntimeError,
) -> bool:
    delay = min(
        MAX_BACKOFF_SECONDS,
        2 ** min(dispatch.attempt_count, 6),
    )
    error_code = str(error)[:80] or "jobs_broker_unavailable"
    with SessionLocal() as db:
        changed = job_repository.retry_dispatch(
            db,
            dispatch_id=dispatch.dispatch_id,
            attempt_count=dispatch.attempt_count,
            available_at=datetime.now(UTC) + timedelta(seconds=delay),
            error_code=error_code,
            error_detail=type(error).__name__,
        )
        db.commit()
    return changed


def dispatch_pending_jobs_once(
    *,
    limit: int = DISPATCH_BATCH_SIZE,
    recover_conversation: Callable[[Session, DurableJob], None] | None = None,
    recover_unclaimed_pdf: Callable[[Session, DurableJob], None] | None = None,
) -> int:
    """Publish outside a DB transaction, then persist each delivery outcome."""
    started = monotonic()
    published_count = 0
    dispatches = _reserve_dispatches(
        limit=limit,
        recover_conversation=recover_conversation,
        recover_unclaimed_pdf=recover_unclaimed_pdf,
    )
    with instrumented_span(
        "jobs.outbox.dispatch",
        attributes={"jobs.dispatch.batch_size": len(dispatches)},
    ):
        for dispatch in dispatches:
            record_histogram(
                "scholens.jobs.queue_age",
                max(
                    0,
                    (datetime.now(UTC) - dispatch.enqueued_at).total_seconds(),
                ),
                unit="s",
                attributes={"queue": dispatch.queue},
            )
            status = "published"
            try:
                jobs_client.publish_task(
                    task_name=dispatch.task_name,
                    queue=dispatch.queue,
                    job_id=str(dispatch.job_id),
                    kwargs=dispatch.kwargs,
                    headers={
                        "scholens-correlation-id": str(dispatch.correlation_id),
                        "scholens-causation-id": str(dispatch.origin_operation_id),
                        **(
                            {"scholens-actor-id": str(dispatch.requested_by_id)}
                            if dispatch.requested_by_id is not None
                            else {}
                        ),
                    },
                )
            except RuntimeError as exc:
                status = "retry"
                changed = _record_publish_failure(dispatch, error=exc)
                logger.warning(
                    "jobs.outbox.publish_failed",
                    extra={
                        "job_id": str(dispatch.job_id),
                        "attempt": dispatch.attempt_count,
                        "exception_type": type(exc).__name__,
                        "lease_owned": changed,
                    },
                )
            else:
                if _record_publish_success(dispatch):
                    published_count += 1
                else:
                    status = "lease_superseded"
                    logger.warning(
                        "jobs.outbox.lease_superseded",
                        extra={
                            "job_id": str(dispatch.job_id),
                            "attempt": dispatch.attempt_count,
                        },
                    )
            add_counter(
                "scholens.jobs.outbox.dispatches",
                attributes={"status": status, "queue": dispatch.queue},
            )
    record_histogram(
        "scholens.jobs.outbox.batch_duration",
        (monotonic() - started) * 1000,
        attributes={"status": "published" if published_count else "idle_or_failed"},
    )
    return published_count


async def run_job_dispatcher(
    stop: asyncio.Event,
    *,
    wakeup: JobDispatcherWakeup | None = None,
    recover_conversation: Callable[[Session, DurableJob], None] | None = None,
    recover_unclaimed_pdf: Callable[[Session, DurableJob], None] | None = None,
) -> None:
    """Continuously drain the outbox without blocking the ASGI event loop."""
    idle_wakeup = wakeup or JobDispatcherWakeup()
    while not stop.is_set():
        try:
            published = await asyncio.to_thread(
                dispatch_pending_jobs_once,
                recover_conversation=recover_conversation,
                recover_unclaimed_pdf=recover_unclaimed_pdf,
            )
        except Exception:
            logger.exception("jobs.outbox.dispatch_failed")
            published = 0
        if published:
            continue
        await idle_wakeup.wait(stop, timeout=DISPATCH_IDLE_SECONDS)
