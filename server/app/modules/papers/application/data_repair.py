"""Administrator-only bounded data repair and incident recovery use cases.

The MCP tooling audit found production annotation anchors whose offsets do
not cover the quote and current completed job results whose ``s3_object_key``
does not match the document, plus canonical text containing Unicode replacement
characters. These commands repair only candidates that can be identified from
durable local evidence, in bounded restartable batches. Every command is
dry-run by default; ``--apply`` is the explicit opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext

ANNOTATION_OFFSETS_FIXED = OperationAction("research.annotation_offsets_fixed")
CONTAMINATED_DOCUMENTS_REPROCESSED = OperationAction(
    "papers.contaminated_documents_reprocessed"
)
STUCK_PAPER_INGESTION_RECOVERED = OperationAction("papers.stuck_ingestion_recovered")
UNICODE_REPLACEMENT_DOCUMENTS_REPROCESSED = OperationAction(
    "papers.unicode_replacement_documents_reprocessed"
)
UNICODE_REPLACEMENT_REPAIR_REVISION = "unicode-replacement-v1"
UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE = 50


@dataclass(frozen=True, slots=True)
class AnnotationOffsetRepairResult:
    candidates: int
    fixed: int
    unresolved: int
    sample_unresolved_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReprocessResult:
    candidates: int
    reprocessed: int
    sample_job_ids: tuple[str, ...] = ()
    enqueued: int = 0
    scanned: int = 0
    skipped: int = 0
    work_bytes: int = 0
    sample_document_ids: tuple[str, ...] = ()


class DataRepairGateway(Protocol):
    def fix_annotation_offsets(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> AnnotationOffsetRepairResult: ...

    def reprocess_contaminated_documents(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult: ...

    def reprocess_unicode_replacement_documents(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult: ...

    def recover_stuck_paper_ingestion(
        self,
        *,
        job_id: UUID,
        min_age_seconds: int,
        apply: bool,
    ) -> ReprocessResult: ...


class DataRepair:
    """Bounded, administrator-guarded data repair and recovery use cases."""

    def __init__(
        self,
        gateway: DataRepairGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )

    def fix_annotation_offsets(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch_size: int,
        apply: bool,
    ) -> AnnotationOffsetRepairResult:
        self._require_admin(actor)
        result = self._gateway.fix_annotation_offsets(
            batch_size=batch_size,
            apply=apply,
        )
        if apply and result.fixed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ANNOTATION_OFFSETS_FIXED,
                resources=(ResourceRef("annotation_threads", "start_offset"),),
            )
        return result

    def reprocess_contaminated_documents(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult:
        self._require_admin(actor)
        result = self._gateway.reprocess_contaminated_documents(
            batch_size=batch_size,
            apply=apply,
        )
        if apply and result.reprocessed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONTAMINATED_DOCUMENTS_REPROCESSED,
                resources=(ResourceRef("jobs", "pdf_process"),),
            )
        return result

    def reprocess_unicode_replacement_documents(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult:
        self._require_admin(actor)
        if not 1 <= batch_size <= UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE:
            raise ValueError(
                "Unicode replacement repair batch size must be between 1 and "
                f"{UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE}"
            )
        result = self._gateway.reprocess_unicode_replacement_documents(
            batch_size=batch_size,
            apply=apply,
        )
        if apply and result.reprocessed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=UNICODE_REPLACEMENT_DOCUMENTS_REPROCESSED,
                resources=(ResourceRef("jobs", UNICODE_REPLACEMENT_REPAIR_REVISION),),
            )
        return result

    def recover_stuck_paper_ingestion(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        min_age_seconds: int,
        apply: bool,
    ) -> ReprocessResult:
        self._require_admin(actor)
        result = self._gateway.recover_stuck_paper_ingestion(
            job_id=job_id,
            min_age_seconds=min_age_seconds,
            apply=apply,
        )
        if apply and result.reprocessed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=STUCK_PAPER_INGESTION_RECOVERED,
                resources=(ResourceRef("job", str(job_id)),),
            )
        return result


__all__ = [
    "AnnotationOffsetRepairResult",
    "DataRepair",
    "DataRepairGateway",
    "ReprocessResult",
    "UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE",
    "UNICODE_REPLACEMENT_REPAIR_REVISION",
]
