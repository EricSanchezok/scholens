"""SQLAlchemy gateway for bounded legacy data repair.

Repairs target only rows written by the pre-fix pipelines and follow the
established operator-maintenance shape: candidate counting first, then a
bounded batch of ordinary row DML inside one transaction when ``apply``
is set. The runtime role never receives trigger or table DDL privileges.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.models import (
    Document,
    DurableJob,
    UploadReservation,
)
from app.llm.utils import find_offsets
from app.modules.papers.application.data_repair import (
    AnnotationOffsetRepairResult,
    CitationPurgeResult,
    DataRepairGateway,
    PublishDateRepairResult,
    ReprocessResult,
)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BAD_OFFSET_RATIO = 0.5
_PROVIDER_FILLED_BY = frozenset({"resolve_paper_citation", "get_paper_citation"})
_CLEARABLE_CITATION_FIELDS = ("publisher", "doi", "journal")


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


class SqlDataRepair(DataRepairGateway):
    def __init__(
        self,
        db: Session,
        *,
        reprocess_enqueuer: ReprocessEnqueuer,
    ) -> None:
        self._db = db
        self._reprocess_enqueuer = reprocess_enqueuer

    def fix_publish_dates(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> PublishDateRepairResult:
        column_type = self._db.scalar(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'scholens'
                  AND table_name = 'documents'
                  AND column_name = 'publish_date'
                """
            )
        )
        candidates = int(
            self._db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM scholens.documents AS document
                    WHERE document.publish_date IS NOT NULL
                      AND document.publish_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                    """
                )
            )
            or 0
        )
        if not apply or candidates == 0:
            return PublishDateRepairResult(
                candidates=candidates,
                fixed=0,
                column_type=str(column_type) if column_type else None,
            )
        rows = self._db.execute(
            text(
                """
                SELECT document.id, document.publish_date
                FROM scholens.documents AS document
                WHERE document.publish_date IS NOT NULL
                  AND document.publish_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                ORDER BY document.id
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).all()
        updates = []
        for document_id, publish_date in rows:
            raw = str(publish_date)
            if not _DATE_ONLY.match(raw):
                continue
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                continue
            updates.append({"document_id": document_id, "publish_date": parsed})
        if updates:
            self._db.execute(
                text(
                    """
                    UPDATE scholens.documents AS document
                    SET publish_date = :publish_date
                    WHERE document.id = :document_id
                    """
                ),
                updates,
            )
        return PublishDateRepairResult(
            candidates=candidates,
            fixed=len(updates),
            column_type=str(column_type) if column_type else None,
        )

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
                    thread.end_offset - thread.start_offset < 1
                    OR char_length(thread.quote_text) = 0
                    OR (
                      thread.end_offset - thread.start_offset
                    ) * 1.0 / char_length(thread.quote_text) < :ratio
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

    def purge_bad_citations(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> CitationPurgeResult:
        rows = self._db.execute(
            text(
                """
                SELECT document.id, document.title, document.publisher,
                       document.doi, document.journal,
                       document.field_provenance
                FROM scholens.documents AS document
                WHERE document.title IS NOT NULL
                  AND document.field_provenance IS NOT NULL
                  AND (
                    (document.publisher IS NOT NULL
                     AND document.field_provenance ? 'publisher')
                    OR (document.doi IS NOT NULL
                        AND document.field_provenance ? 'doi')
                    OR (document.journal IS NOT NULL
                        AND document.field_provenance ? 'journal')
                  )
                ORDER BY document.id
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).all()
        candidates = len(rows)
        purged: list[str] = []
        if not apply or not rows:
            return CitationPurgeResult(
                candidates=candidates,
                purged=0,
                sample_document_ids=tuple(str(row.id) for row in rows[:5]),
            )
        for row in rows:
            provenance = dict(row.field_provenance or {})
            clear: list[str] = []
            for field_name in _CLEARABLE_CITATION_FIELDS:
                if getattr(row, field_name) is None:
                    continue
                filled = provenance.get(field_name)
                if not isinstance(filled, dict):
                    continue
                if filled.get("filled_by") not in _PROVIDER_FILLED_BY:
                    continue
                clear.append(field_name)
            if not clear:
                continue
            # Clear only provider-derived values; keep field_provenance so the
            # audit trail survives and the next resolve re-fetches through the
            # new title-consistency path.
            assignments = ", ".join(f"{name} = NULL" for name in clear)
            self._db.execute(
                text(
                    f"""
                    UPDATE scholens.documents AS document
                    SET {assignments}
                    WHERE document.id = :document_id
                    """
                ),
                {"document_id": row.id},
            )
            purged.append(str(row.id))
        return CitationPurgeResult(
            candidates=candidates,
            purged=len(purged),
            sample_document_ids=tuple(purged[:5]),
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
                  AND job.status IN ('completed', 'failed')
                  AND job.document_id IS NOT NULL
                  AND job.requested_by_id IS NOT NULL
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
        if source.requested_by_id is None:
            return False
        document = self._db.get(Document, source.document_id)
        if document is None:
            return False
        reservation = self._db.get(UploadReservation, job_id)
        return self._reprocess_enqueuer(
            db=self._db,
            source=source,
            document=document,
            reservation=reservation,
        )


__all__ = ["SqlDataRepair"]
