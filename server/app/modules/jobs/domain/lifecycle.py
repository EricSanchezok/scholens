"""Pure durable-job lifecycle and lease decisions."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.shared.domain.enums import JobStatus
from scholens_job_contracts import ZOTERO_CALLBACK_LEASE_SECONDS

DEFAULT_JOB_LEASE = timedelta(hours=1)
DEFAULT_CALLBACK_LEASE = timedelta(seconds=ZOTERO_CALLBACK_LEASE_SECONDS)


def can_claim_job(
    status: JobStatus,
    *,
    lease_expires_at: datetime | None,
    now: datetime,
) -> bool:
    return status is JobStatus.PENDING or (
        status is JobStatus.RUNNING
        and lease_expires_at is not None
        and lease_expires_at < now
    )


def can_heartbeat_job(status: JobStatus) -> bool:
    return status is JobStatus.RUNNING


def can_recover_job(
    status: JobStatus,
    *,
    lease_expires_at: datetime | None,
    now: datetime,
) -> bool:
    return (
        status is JobStatus.RUNNING
        and lease_expires_at is not None
        and lease_expires_at < now
    )


def can_complete_job(status: JobStatus) -> bool:
    return status in {JobStatus.PENDING, JobStatus.RUNNING}


def can_fail_job(status: JobStatus) -> bool:
    return status in {JobStatus.PENDING, JobStatus.RUNNING}


def can_cancel_job(status: JobStatus) -> bool:
    return status in {JobStatus.PENDING, JobStatus.RUNNING}


def is_terminal_job(status: JobStatus) -> bool:
    return status in {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
