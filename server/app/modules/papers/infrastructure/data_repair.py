"""SQLAlchemy gateway for bounded data repair and incident recovery.

Repairs target only rows written by the pre-fix pipelines and follow the
established operator-maintenance shape: bounded candidate batches and ordinary
row DML inside one transaction when ``apply`` is set. Unicode repair selection
uses keyset pages, byte/work caps, row locks, and per-row savepoints. The
runtime role never receives trigger or table DDL privileges.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from scholens_job_contracts import (
    PDF_TEXT_REPAIR_MAX_ATTEMPTS,
    UNICODE_REPLACEMENT_CHARACTER,
)
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.models import (
    Document,
    DurableJob,
    JobDispatch,
    UploadReservation,
)
from app.llm.utils import find_offsets
from app.modules.jobs.domain import MAINTENANCE_JOB_VISIBILITY
from app.modules.papers.application.data_repair import (
    AnnotationOffsetRepairResult,
    DataRepairGateway,
    ReprocessResult,
    UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE,
    UNICODE_REPLACEMENT_REPAIR_REVISION,
)

_BAD_OFFSET_RATIO = 0.5
_UNICODE_REPAIR_SCAN_PAGE_SIZE = 16
_UNICODE_REPAIR_SCAN_MULTIPLIER = 4
_UNICODE_REPAIR_MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
_UNICODE_REPAIR_WORK_BUDGET_BYTES = 64 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _UnicodeRepairCandidate:
    document_id: uuid.UUID
    source_job_id: uuid.UUID


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
        repair_revision: str | None = None,
        source_content_digest: str | None = None,
        repair_attempt: int | None = None,
    ) -> uuid.UUID | None: ...


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
            new_job_id = self._reprocess_one(job_id=row.id)
            if new_job_id is not None:
                reprocessed.append(str(new_job_id))
        return ReprocessResult(
            candidates=candidates,
            reprocessed=len(reprocessed),
            sample_job_ids=tuple(reprocessed[:5]),
            enqueued=len(reprocessed),
        )

    def reprocess_unicode_replacement_documents(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ReprocessResult:
        bounded_batch_size = min(
            max(batch_size, 1),
            UNICODE_REPLACEMENT_REPAIR_MAX_BATCH_SIZE,
        )
        candidates, scanned, skipped, work_bytes = self._unicode_repair_candidates(
            batch_size=bounded_batch_size,
            lock=apply,
        )
        document_ids = tuple(str(row.document_id) for row in candidates)
        if not apply or not candidates:
            return ReprocessResult(
                candidates=len(candidates),
                reprocessed=0,
                enqueued=0,
                scanned=scanned,
                skipped=skipped,
                work_bytes=work_bytes,
                sample_document_ids=document_ids[:5],
            )

        repair_job_ids: list[str] = []
        stale_or_failed = 0
        for row in candidates:
            try:
                # One candidate cannot poison the rest of the bounded batch.
                # The outer transaction retains the candidate row locks while
                # this savepoint rolls back only a stale or failed enqueue.
                with self._db.begin_nested():
                    repair_job_id = self._enqueue_unicode_repair(
                        source_job_id=row.source_job_id,
                        document_id=row.document_id,
                    )
            except (RuntimeError, ValueError, SQLAlchemyError) as exc:
                stale_or_failed += 1
                error_code = (
                    str(exc)
                    if isinstance(exc, RuntimeError) and str(exc).startswith("pdf_")
                    else type(exc).__name__
                )
                _LOGGER.warning(
                    "unicode replacement repair candidate skipped",
                    extra={
                        "document_id": str(row.document_id),
                        "error_code": error_code,
                    },
                )
                continue
            if repair_job_id is None:
                stale_or_failed += 1
                continue
            repair_job_ids.append(str(repair_job_id))
        enqueued = len(repair_job_ids)
        return ReprocessResult(
            candidates=len(candidates),
            reprocessed=enqueued,
            sample_job_ids=tuple(repair_job_ids[:5]),
            enqueued=enqueued,
            scanned=scanned,
            skipped=skipped + stale_or_failed,
            work_bytes=work_bytes,
            sample_document_ids=document_ids[:5],
        )

    def _unicode_repair_candidates(
        self,
        *,
        batch_size: int,
        lock: bool,
    ) -> tuple[list[_UnicodeRepairCandidate], int, int, int]:
        """Select a bounded repair batch without materializing raw text.

        Candidate pages are keyset-ordered by Document primary key. PostgreSQL
        computes the corruption predicate and byte size; Python receives only
        identifiers and sizes. Apply mode locks each selected Document with
        ``SKIP LOCKED`` so concurrent operators do not enqueue duplicate work.
        A completed outcome closes its canonical source generation, including
        an applied repair that became the Document's current source Job.
        """

        candidates: list[_UnicodeRepairCandidate] = []
        after_id: uuid.UUID | None = None
        scanned = 0
        skipped = 0
        work_bytes = 0
        scan_limit = batch_size * _UNICODE_REPAIR_SCAN_MULTIPLIER
        lock_clause = "FOR UPDATE OF document SKIP LOCKED" if lock else ""
        while len(candidates) < batch_size and scanned < scan_limit:
            page_limit = min(
                _UNICODE_REPAIR_SCAN_PAGE_SIZE,
                scan_limit - scanned,
            )
            rows = self._db.execute(
                text(
                    f"""
                    SELECT document.id AS document_id,
                           source.id AS source_job_id,
                           octet_length(document.raw_content) AS content_bytes
                    FROM scholens.documents AS document
                    JOIN scholens.jobs AS source
                      ON source.id = document.processing_job_id
                    WHERE document.processing_status = 'completed'
                      AND document.raw_content IS NOT NULL
                      AND position(U&'\\FFFD' in document.raw_content) > 0
                      AND octet_length(document.raw_content) <= :max_document_bytes
                      AND source.operation = 'pdf_process'
                      AND source.status = 'completed'
                      AND source.requested_by_id IS NOT NULL
                      AND (
                        CAST(:after_id AS uuid) IS NULL
                        OR document.id > CAST(:after_id AS uuid)
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM scholens.jobs AS repair
                        WHERE repair.document_id = document.id
                          AND repair.payload->>'job_visibility' = :visibility
                          AND repair.payload->>'repair_kind' = 'unicode_replacement'
                          AND repair.payload->>'repair_revision' = :revision
                          AND (
                            repair.status IN ('pending', 'running')
                            OR (
                              repair.status = 'completed'
                              AND (
                                repair.id = source.id
                                OR repair.payload->>'repair_source_job_id'
                                  = source.id::text
                              )
                            )
                          )
                      )
                      AND COALESCE((
                        SELECT max(
                          CASE
                            WHEN repair.payload->>'repair_attempt' ~ '^[1-9][0-9]*$'
                            THEN (repair.payload->>'repair_attempt')::integer
                            ELSE 1
                          END
                        )
                        FROM scholens.jobs AS repair
                        WHERE repair.document_id = document.id
                          AND repair.payload->>'job_visibility' = :visibility
                          AND repair.payload->>'repair_kind' = 'unicode_replacement'
                          AND repair.payload->>'repair_revision' = :revision
                          AND repair.payload->>'repair_source_job_id' = source.id::text
                          AND repair.status IN ('failed', 'cancelled')
                      ), 0) < :max_attempts
                    ORDER BY document.id
                    LIMIT :limit
                    {lock_clause}
                    """
                ),
                {
                    "after_id": str(after_id) if after_id is not None else None,
                    "limit": page_limit,
                    "max_attempts": PDF_TEXT_REPAIR_MAX_ATTEMPTS,
                    "max_document_bytes": _UNICODE_REPAIR_MAX_DOCUMENT_BYTES,
                    "revision": UNICODE_REPLACEMENT_REPAIR_REVISION,
                    "visibility": MAINTENANCE_JOB_VISIBILITY,
                },
            ).all()
            if not rows:
                break
            after_id = rows[-1].document_id
            scanned += len(rows)
            for row in rows:
                content_bytes = int(row.content_bytes or 0)
                if (
                    content_bytes <= 0
                    or content_bytes > _UNICODE_REPAIR_MAX_DOCUMENT_BYTES
                    or work_bytes + content_bytes > _UNICODE_REPAIR_WORK_BUDGET_BYTES
                ):
                    skipped += 1
                    continue
                candidates.append(
                    _UnicodeRepairCandidate(
                        document_id=row.document_id,
                        source_job_id=row.source_job_id,
                    )
                )
                work_bytes += content_bytes
                if len(candidates) >= batch_size:
                    break
            if work_bytes >= _UNICODE_REPAIR_WORK_BUDGET_BYTES:
                break
        return candidates, scanned, skipped, work_bytes

    def _enqueue_unicode_repair(
        self,
        *,
        source_job_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> uuid.UUID | None:
        source = self._db.scalar(
            select(DurableJob).where(DurableJob.id == source_job_id).with_for_update()
        )
        document = self._db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if source is None or document is None:
            return None
        if (
            source.requested_by_id is None
            or source.status != "completed"
            or source.operation != "pdf_process"
            or source.document_id != document.id
            or document.processing_status != "completed"
            or document.processing_job_id != source.id
            or document.raw_content is None
            or UNICODE_REPLACEMENT_CHARACTER not in document.raw_content
        ):
            return None

        # Scholens does not require pgcrypto. Compute SHA-256 only after the
        # byte-bounded candidate is locked, so at most one raw text value is
        # materialized at a time without adding a production DB extension.
        source_content_digest = hashlib.sha256(
            document.raw_content.encode("utf-8")
        ).hexdigest()
        repair_attempt = self._next_unicode_repair_attempt(
            document_id=document.id,
            source_job_id=source.id,
            source_content_digest=source_content_digest,
        )
        if repair_attempt is None:
            return None
        reservation = self._db.get(UploadReservation, source.id)
        return self._reprocess_enqueuer(
            db=self._db,
            source=source,
            document=document,
            reservation=reservation,
            repair_revision=UNICODE_REPLACEMENT_REPAIR_REVISION,
            source_content_digest=source_content_digest,
            repair_attempt=repair_attempt,
        )

    def _next_unicode_repair_attempt(
        self,
        *,
        document_id: uuid.UUID,
        source_job_id: uuid.UUID,
        source_content_digest: str,
    ) -> int | None:
        state = self._db.execute(
            text(
                """
                SELECT COALESCE(
                         bool_or(repair.status IN ('pending', 'running', 'completed')),
                         false
                       ) AS blocked,
                       COALESCE(
                         max(
                           CASE
                             WHEN repair.status IN ('failed', 'cancelled') THEN
                               CASE
                                 WHEN repair.payload->>'repair_attempt'
                                      ~ '^[1-9][0-9]*$'
                                 THEN (repair.payload->>'repair_attempt')::integer
                                 ELSE 1
                               END
                             ELSE 0
                           END
                         ),
                         0
                       ) AS highest_attempt
                FROM scholens.jobs AS repair
                WHERE repair.document_id = :document_id
                  AND repair.payload->>'job_visibility' = :visibility
                  AND repair.payload->>'repair_kind' = 'unicode_replacement'
                  AND repair.payload->>'repair_revision' = :revision
                  AND repair.payload->>'repair_source_job_id' = :source_job_id
                  AND repair.payload->>'repair_source_content_digest' = :source_digest
                """
            ),
            {
                "document_id": document_id,
                "revision": UNICODE_REPLACEMENT_REPAIR_REVISION,
                "source_digest": source_content_digest,
                "source_job_id": str(source_job_id),
                "visibility": MAINTENANCE_JOB_VISIBILITY,
            },
        ).one()
        if state.blocked:
            return None
        highest_attempt = int(state.highest_attempt)
        if highest_attempt >= PDF_TEXT_REPAIR_MAX_ATTEMPTS:
            return None
        return highest_attempt + 1

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

    def _reprocess_one(
        self,
        *,
        job_id: uuid.UUID,
    ) -> uuid.UUID | None:
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
            return None
        if source.requested_by_id is None or source.status != "completed":
            return None
        document = self._db.get(Document, source.document_id)
        if document is None:
            return None
        if (
            document.processing_status != "completed"
            or document.processing_job_id != source.id
        ):
            return None
        reservation = self._db.get(UploadReservation, job_id)
        return self._reprocess_enqueuer(
            db=self._db,
            source=source,
            document=document,
            reservation=reservation,
        )


__all__ = ["SqlDataRepair"]
