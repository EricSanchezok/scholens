"""Versioned effect serialization and restart-safe post-commit delivery."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.jobs.application.callbacks import (
    JobPostCommitAction,
    DeleteJobResultArtifacts,
    RecordJobTelemetry,
    ReleaseJobConcurrency,
    SettleJobUsage,
)
from app.modules.jobs.infrastructure.models import DurableJob, JobResultEffect
from app.shared.domain import JsonValue

_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "release_concurrency": TypeAdapter(ReleaseJobConcurrency),
    "settle_usage": TypeAdapter(SettleJobUsage),
    "record_telemetry": TypeAdapter(RecordJobTelemetry),
    "delete_job_results": TypeAdapter(DeleteJobResultArtifacts),
}
_KINDS = {
    ReleaseJobConcurrency: "release_concurrency",
    SettleJobUsage: "settle_usage",
    RecordJobTelemetry: "record_telemetry",
    DeleteJobResultArtifacts: "delete_job_results",
}


def encode_effect(action: JobPostCommitAction) -> dict[str, JsonValue]:
    kind = _KINDS[type(action)]
    return {
        "version": 1,
        "kind": kind,
        "value": _ADAPTERS[kind].dump_python(action, mode="json"),
    }


def decode_effect(payload: dict[str, JsonValue]) -> JobPostCommitAction:
    kind = payload.get("kind")
    if (
        payload.get("version") != 1
        or not isinstance(kind, str)
        or kind not in _ADAPTERS
    ):
        raise ValueError("job_effect_version_unsupported")
    return cast(JobPostCommitAction, _ADAPTERS[kind].validate_python(payload["value"]))


@dataclass(frozen=True, slots=True)
class ReservedJobEffect:
    job_id: UUID
    generation: int
    ordinal: int
    claim_id: UUID
    action: JobPostCommitAction


class JobEffectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(
        self,
        *,
        job_id: UUID,
        generation: int,
        actions: tuple[JobPostCommitAction, ...],
        available_at: datetime | None = None,
    ) -> None:
        for ordinal, action in enumerate(actions):
            self.db.add(
                JobResultEffect(
                    job_id=job_id,
                    claim_generation=generation,
                    ordinal=ordinal,
                    payload=encode_effect(action),
                    available_at=available_at or datetime.now(UTC),
                )
            )

    def reserve(self, *, now: datetime | None = None) -> ReservedJobEffect | None:
        now = now or datetime.now(UTC)
        other = aliased(JobResultEffect)
        cleanup_ready = and_(
            DurableJob.status.in_(("completed", "failed", "cancelled")),
            DurableJob.completed_at < now - timedelta(days=7),
            ~exists(
                select(other.job_id).where(
                    other.job_id == JobResultEffect.job_id,
                    other.claim_generation > 0,
                    other.status != "applied",
                )
            ),
        )
        row = self.db.scalar(
            select(JobResultEffect)
            .join(DurableJob, DurableJob.id == JobResultEffect.job_id)
            .where(
                JobResultEffect.available_at <= now,
                or_(
                    JobResultEffect.payload["kind"].as_string() != "delete_job_results",
                    cleanup_ready,
                ),
                or_(
                    JobResultEffect.status == "pending",
                    and_(
                        JobResultEffect.status == "applying",
                        JobResultEffect.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(
                JobResultEffect.available_at,
                JobResultEffect.job_id,
                JobResultEffect.ordinal,
            )
            .limit(1)
            .with_for_update(skip_locked=True, of=JobResultEffect)
        )
        if row is None:
            return None
        row.status, row.claim_id = "applying", uuid4()
        row.lease_expires_at = now + timedelta(seconds=180)
        row.attempt_count += 1
        self.db.flush()
        return ReservedJobEffect(
            row.job_id,
            row.claim_generation,
            row.ordinal,
            row.claim_id,
            decode_effect(row.payload),
        )

    def finish(
        self, reservation: ReservedJobEffect, *, error_code: str | None = None
    ) -> bool:
        row = self.db.scalar(
            select(JobResultEffect)
            .where(
                JobResultEffect.job_id == reservation.job_id,
                JobResultEffect.claim_generation == reservation.generation,
                JobResultEffect.ordinal == reservation.ordinal,
            )
            .with_for_update()
        )
        if (
            row is None
            or row.status != "applying"
            or row.claim_id != reservation.claim_id
        ):
            return False
        row.claim_id, row.lease_expires_at = None, None
        row.status = "pending" if error_code else "applied"
        row.error_code = error_code[:80] if error_code else None
        row.available_at = datetime.now(UTC) + timedelta(
            seconds=min(300, 2 ** min(9, row.attempt_count))
        )
        return True
