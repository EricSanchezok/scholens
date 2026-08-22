"""SQLAlchemy gateway for bounded data repair and incident recovery.

Repairs target only rows written by the pre-fix pipelines and follow the
established operator-maintenance shape: one bounded candidate batch and
ordinary row DML inside one transaction when ``apply`` is set. The runtime
role never receives trigger or table DDL privileges.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database.models import (
    Document,
    DurableJob,
    JobDispatch,
    UploadReservation,
)
from app.llm.utils import find_offsets
from app.modules.papers.application.data_repair import (
    AnnotationOffsetRepairResult,
    DataRepairGateway,
    ReprocessResult,
)

_BAD_OFFSET_RATIO = 0.5


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


class ReprocessEnqueuer(Protocol):
    """Composition-injected enqueuer for one contaminated document.

    Implemented in ``app.bootstrap.adapters.data_repair_jobs`` so the papers
    module never reaches into another module's infrastructure.
    """

    def __call__(
        self,
        *,
        db: Session,
        source: DurableJob,
        document: Document,
        reservation: UploadReservation | None,
    ) -> bool: ...


class StuckJobRecoverer(Protocol):
    def __call__(self, db: Session, source: DurableJob) -> None: ...


class SqlDataRepair(DataRepairGateway):
    def __init__(
        self,
        db: Session,
        *,
        reprocess_enqueuer: ReprocessEnqueuer,
        stuck_job_recoverer: StuckJobRecoverer,
    ) -> None:
        self._db = db
        self._reprocess_enqueuer = reprocess_enqueuer
        self._stuck_job_recoverer = stuck_job_recoverer

    def fix_annotation_offsets(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> AnnotationOffsetRepairResult:
        rows = self._db.execute(
            text(
                """
                SELECT thread.research_item_id,
                       thread.quote_text,
                       thread.start_offset,
                       thread.end_offset,
                       thread.position,
                       document.raw_content
                FROM scholens.annotation_threads AS thread
                JOIN scholens.research_items AS item
                  ON item.id = thread.research_item_id
                JOIN scholens.documents AS document
                  ON document.id = item.target_document_id
                WHERE thread.start_offset IS NOT NULL
                  AND thread.end_offset IS NOT NULL
                  AND thread.start_offset < thread.end_offset
                  AND document.raw_content IS NOT NULL
                  AND (
                    char_length(thread.quote_text) = 0
                    OR (
                      thread.end_offset - thread.start_offset
                    ) * 1.0 / NULLIF(char_length(thread.quote_text), 0) < :ratio
                  )
                ORDER BY thread.research_item_id
                LIMIT :limit
                """
            ),
            {
                "ratio": _BAD_OFFSET_RATIO,
                "limit": batch_size,
            },
        ).all()
        candidates = len(rows)
        fixed = 0
        unresolved: list[str] = []
        if not apply or not rows:
            return AnnotationOffsetRepairResult(
                candidates=candidates,
                fixed=0,
                unresolved=candidates,
                sample_unresolved_ids=tuple(
                    str(row.research_item_id) for row in rows[:5]
                ),
            )
        for row in rows:
            quote = row.quote_text
            raw_content = row.raw_content or ""
            start, end = find_offsets(quote, raw_content)
            if start < 0 or end <= start:
                unresolved.append(str(row.research_item_id))
                continue
            # With repeated verbatim quotes there is no durable evidence that
            # the first occurrence is the intended anchor. Leave those rows
            # untouched for manual review instead of moving them arbitrarily.
            if raw_content.find(quote, end) >= 0:
                unresolved.append(str(row.research_item_id))
                continue
            window = raw_content[start:end]
            if _normalize_whitespace(window) != _normalize_whitespace(quote):
                unresolved.append(str(row.research_item_id))
                continue
            position = dict(row.position or {})
            position["start_offset"] = start
            position["end_offset"] = end
            self._db.execute(
                text(
                    """
                    UPDATE scholens.annotation_threads AS thread
                    SET start_offset = :start_offset,
                        end_offset = :end_offset,
                        position = CAST(:position AS jsonb)
                    WHERE thread.research_item_id = :thread_id
                    """
                ),
                {
                    "thread_id": row.research_item_id,
                    "start_offset": start,
                    "end_offset": end,
                    "position": json.dumps(position),
                },
            )
            fixed += 1
        return AnnotationOffsetRepairResult(
            candidates=candidates,
            fixed=fixed,
            unresolved=len(unresolved),
            sample_unresolved_ids=tuple(unresolved[:5]),
        )

    def reprocess_contaminated_documents(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult:
        rows = self._db.execute(
            text(
                """
                SELECT job.id
                FROM scholens.jobs AS job
                JOIN scholens.documents AS document
                  ON document.id = job.document_id
                WHERE job.operation = 'pdf_process'
                  AND job.status = 'completed'
                  AND job.document_id IS NOT NULL
                  AND job.requested_by_id IS NOT NULL
                  AND document.processing_status = 'completed'
                  AND document.processing_job_id = job.id
                  AND job.result IS NOT NULL
                  AND job.result ? 's3_object_key'
                  AND job.result->>'s3_object_key' IS DISTINCT FROM document.s3_object_key
                  AND NOT EXISTS (
                    SELECT 1
                    FROM scholens.jobs AS reprocess
                    WHERE reprocess.idempotency_key = 'pdf-reprocess:' || job.id::text
                  )
                ORDER BY job.id
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).all()
        candidates = len(rows)
        if not apply or not rows:
            return ReprocessResult(
                candidates=candidates,
                reprocessed=0,
                sample_job_ids=tuple(str(row.id) for row in rows[:5]),
            )
        # Reprocessing enqueues a fresh, dispatchable pdf_process job for the
        # same document source. The original terminal row stays immutable; the
        # new job supersedes it through the ordinary worker + webhook path.
        reprocessed: list[str] = []
        for row in rows:
            if self._reprocess_one(job_id=row.id):
                reprocessed.append(str(row.id))
        return ReprocessResult(
            candidates=candidates,
            reprocessed=len(reprocessed),
            sample_job_ids=tuple(reprocessed[:5]),
        )

    def recover_stuck_paper_ingestion(
        self,
        *,
        job_id: uuid.UUID,
        min_age_seconds: int,
        apply: bool,
    ) -> ReprocessResult:
        cutoff = datetime.now(UTC) - timedelta(seconds=min_age_seconds)
        statement = (
            select(DurableJob)
            .join(JobDispatch, JobDispatch.job_id == DurableJob.id)
            .join(Document, Document.id == DurableJob.document_id)
            .where(
                DurableJob.id == job_id,
                DurableJob.operation == "pdf_process",
                DurableJob.status == "pending",
                DurableJob.requested_by_id.is_not(None),
                Document.processing_status == "processing",
                Document.processing_job_id == DurableJob.id,
                JobDispatch.status == "published",
                JobDispatch.published_at.is_not(None),
                JobDispatch.published_at < cutoff,
            )
        )
        if apply:
            statement = statement.with_for_update()
        source = self._db.scalar(statement)
        recovery_attempt = source.payload.get("recovery_attempt", 0) if source else 0
        if source is None or (
            isinstance(recovery_attempt, int)
            and not isinstance(recovery_attempt, bool)
            and recovery_attempt >= 1
        ):
            return ReprocessResult(candidates=0, reprocessed=0)
        if not apply:
            return ReprocessResult(
                candidates=1,
                reprocessed=0,
                sample_job_ids=(str(source.id),),
            )
        self._stuck_job_recoverer(self._db, source)
        return ReprocessResult(
            candidates=1,
            reprocessed=1,
            sample_job_ids=(str(source.id),),
        )

    def _reprocess_one(self, *, job_id: uuid.UUID) -> bool:
        """Enqueue one dispatchable reprocess job for a contaminated document.

        The candidate SQL already guarantees a non-null requester; the new job
        reuses the original requester, correlation and origin so the terminal
        webhook can resume the same actor, and reuses the document's
        content-addressed source S3 key. The composition-injected enqueuer
        creates the durable job, outbox dispatch and upload reservation
        (``reference_created=False`` so existing memberships are never torn
        down, ``reserved_reference_count=0`` so no reference quota is
        consumed). The original terminal job row stays immutable.
        """
        source = self._db.get(DurableJob, job_id)
        if source is None or source.document_id is None:
            return False
        if source.requested_by_id is None or source.status != "completed":
            return False
        document = self._db.get(Document, source.document_id)
        if document is None:
            return False
        if (
            document.processing_status != "completed"
            or document.processing_job_id != source.id
        ):
            return False
        reservation = self._db.get(UploadReservation, job_id)
        return self._reprocess_enqueuer(
            db=self._db,
            source=source,
            document=document,
            reservation=reservation,
        )


__all__ = ["SqlDataRepair"]
