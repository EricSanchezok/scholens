"""Administrator-owned recovery policy and append-only result attribution."""

from dataclasses import dataclass
import re
from typing import Protocol
from uuid import UUID

from scholens_job_contracts import JobResultManifest

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.jobs.application.actions import JOB_COMPLETED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor, OperationContext

JOB_RESULT_RECOVERED = OperationAction("job.result_recovered")
JOB_FAILURE_RECLASSIFIED = OperationAction("job.failure_reclassified")


@dataclass(frozen=True, slots=True)
class RecoveredDocumentResult:
    owner: Actor
    operation: OperationContext
    changes: tuple[OperationChange, ...]
    generation: int
    attempts: int
    previous_error: str | None


@dataclass(frozen=True, slots=True)
class ReclassifiedPdfFailure:
    changed: bool
    previous_error: str | None
    error_code: str
    result_sha256: str


class DocumentResultRecoveryGateway(Protocol):
    def manifest(self, *, job_id: UUID) -> JobResultManifest: ...
    def apply(
        self, *, job_id: UUID, manifest: JobResultManifest, payload: dict[str, object]
    ) -> RecoveredDocumentResult: ...
    def reconcile_pdf_failure(self, *, job_id: UUID) -> ReclassifiedPdfFailure: ...


class DocumentResultRecovery:
    def __init__(
        self, gateway: DocumentResultRecoveryGateway, *, journal: OperationJournal
    ) -> None:
        self._gateway, self._journal = gateway, journal

    @staticmethod
    def _authorize(actor: Actor) -> None:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_admin=actor.is_admin,
                is_blocked=actor.is_blocked,
            )
        )

    def manifest(self, *, actor: Actor, job_id: UUID) -> JobResultManifest:
        self._authorize(actor)
        return self._gateway.manifest(job_id=job_id)

    def apply(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        manifest: JobResultManifest,
        payload: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        self._authorize(actor)
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", reason) is None:
            raise ValueError("recovery_reason_must_be_a_bounded_identifier")
        result = self._gateway.apply(job_id=job_id, manifest=manifest, payload=payload)
        self._journal.append_many(
            actor=result.owner, operation=result.operation, changes=result.changes
        )
        self._journal.append(
            actor=result.owner,
            operation=result.operation,
            action=JOB_COMPLETED,
            resources=(ResourceRef("job", str(job_id)),),
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=JOB_RESULT_RECOVERED,
            resources=(
                ResourceRef("job", str(job_id)),
                ResourceRef("result_sha256", manifest.sha256),
                ResourceRef("generation", str(result.generation)),
                ResourceRef("recovery_reason", reason),
            ),
        )
        return {
            "job_id": str(job_id),
            "status": "completed",
            "generation": result.generation,
            "application_attempts": result.attempts,
            "previous_apply_error": result.previous_error,
        }

    def reconcile_pdf_failure(
        self, *, actor: Actor, operation: OperationContext, job_id: UUID
    ) -> dict[str, object]:
        self._authorize(actor)
        result = self._gateway.reconcile_pdf_failure(job_id=job_id)
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILURE_RECLASSIFIED,
                resources=(
                    ResourceRef("job", str(job_id)),
                    ResourceRef("result_sha256", result.result_sha256),
                    ResourceRef("previous_failure", str(result.previous_error)),
                    ResourceRef("corrected_failure", result.error_code),
                ),
            )
        return {
            "job_id": str(job_id),
            "changed": result.changed,
            "previous_error": result.previous_error,
            "error_code": result.error_code,
        }
