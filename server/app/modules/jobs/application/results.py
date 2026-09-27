"""Transport-independent fenced execution and atomic result application."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from scholens_job_contracts import (
    JobExecutionClaim,
    JobResultManifest,
    JobResultReceipt,
)

from app.modules.jobs.application.callbacks import JobCallbacks, JobCompletionResult
from app.shared.application import Actor, OperationContext


@dataclass(frozen=True, slots=True)
class ReservedJobResult:
    job_id: UUID
    generation: int
    claim_id: UUID
    manifest: JobResultManifest
    request_id: UUID
    delivery_ref: str


class JobResultStore(Protocol):
    def claim(self, *, job_id: UUID, claim_token: UUID) -> JobExecutionClaim: ...
    def heartbeat(
        self, *, job_id: UUID, generation: int, progress_code: str | None = None
    ) -> bool: ...
    def accept(
        self,
        *,
        job_id: UUID,
        manifest: JobResultManifest,
        request_id: UUID,
        delivery_ref: str,
    ) -> JobResultReceipt: ...
    def lock_application(self, reservation: ReservedJobResult) -> bool: ...
    def applied(self, reservation: ReservedJobResult) -> None: ...


class JobResults:
    def __init__(self, store: JobResultStore, callbacks: JobCallbacks) -> None:
        self._store, self._callbacks = store, callbacks

    def claim(self, *, job_id: UUID, claim_token: UUID) -> JobExecutionClaim:
        return self._store.claim(job_id=job_id, claim_token=claim_token)

    def heartbeat(
        self, *, job_id: UUID, generation: int, progress_code: str | None = None
    ) -> JobExecutionClaim:
        claimed = self._store.heartbeat(
            job_id=job_id, generation=generation, progress_code=progress_code
        )
        return JobExecutionClaim(
            claimed=claimed, claim_generation=generation if claimed else None
        )

    def accept(
        self,
        *,
        job_id: UUID,
        manifest: JobResultManifest,
        request_id: UUID,
        delivery_ref: str,
    ) -> JobResultReceipt:
        return self._store.accept(
            job_id=job_id,
            manifest=manifest,
            request_id=request_id,
            delivery_ref=delivery_ref,
        )

    def apply(
        self,
        *,
        reservation: ReservedJobResult,
        actor: Actor | None,
        operation: OperationContext,
        payload: dict[str, object],
    ) -> JobCompletionResult:
        # The execution fence, business projection and inbox acknowledgement
        # share the caller's transaction. A restart cannot apply effects twice.
        if not self._store.lock_application(reservation):
            return JobCompletionResult(value={"accepted": False})
        result = self._callbacks.complete(
            actor=actor,
            operation=operation,
            job_id=reservation.job_id,
            payload=payload,
        )
        self._store.applied(reservation)
        return result
