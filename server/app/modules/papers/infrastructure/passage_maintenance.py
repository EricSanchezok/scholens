"""PostgreSQL passage-index maintenance adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from scholens_ai import EMBEDDING_MODEL_REVISION, semantic_source_digest
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.helpers.postgres import sanitize_for_postgres
from app.modules.papers.application.maintenance import (
    PassageBackfillResult,
    PassageEmbeddingBackfillSnapshot,
    PassageEmbeddingCandidate,
    PassageEmbeddingWrite,
)
from app.modules.papers.infrastructure.models import DocumentPassage
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)


class SqlPassageBackfill:
    def __init__(self, db: Session) -> None:
        self._db = db

    def backfill(self, *, batch_size: int, apply: bool) -> PassageBackfillResult:
        candidates = int(
            self._db.scalar(
                text(
                    """
                    SELECT COUNT(*) FROM scholens.documents AS document
                    WHERE document.raw_content IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM scholens.document_passages AS passage
                        WHERE passage.document_id = document.id
                      )
                    """
                )
            )
            or 0
        )
        if not apply or candidates == 0:
            return PassageBackfillResult(
                candidates=candidates,
                indexed_documents=0,
                indexed_passages=0,
            )

        rows = self._db.execute(
            text(
                """
                SELECT document.id, document.raw_content
                FROM scholens.documents AS document
                WHERE document.raw_content IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM scholens.document_passages AS passage
                    WHERE passage.document_id = document.id
                  )
                ORDER BY document.id
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).all()
        passages: list[dict[str, object]] = []
        for document_id, raw_content in rows:
            sanitized = sanitize_for_postgres(raw_content)
            passages.extend(
                {"document_id": document_id, **passage}
                for passage in document_search_repository.build_passages(sanitized)
            )
        if passages:
            self._db.execute(
                text(
                    """
                    INSERT INTO scholens.document_passages
                        (document_id, start_line, end_line, content)
                    VALUES (:document_id, :start_line, :end_line, :content)
                    ON CONFLICT (document_id, start_line) DO NOTHING
                    """
                ),
                passages,
            )
        return PassageBackfillResult(
            candidates=candidates,
            indexed_documents=len(rows),
            indexed_passages=len(passages),
        )

    def embedding_candidates(
        self, *, batch_size: int
    ) -> PassageEmbeddingBackfillSnapshot:
        needs_embedding = or_(
            DocumentPassage.embedding.is_(None),
            DocumentPassage.embedding_model_revision.is_distinct_from(
                EMBEDDING_MODEL_REVISION
            ),
            DocumentPassage.embedding_source_digest.is_(None),
        )
        eligible = (
            needs_embedding,
            func.length(func.btrim(DocumentPassage.content)) > 0,
        )
        candidates = int(
            self._db.scalar(select(func.count(DocumentPassage.id)).where(*eligible))
            or 0
        )
        rows = self._db.execute(
            select(
                DocumentPassage.id,
                DocumentPassage.document_id,
                DocumentPassage.start_line,
                DocumentPassage.content,
            )
            .where(*eligible)
            .order_by(DocumentPassage.document_id, DocumentPassage.start_line)
            .limit(batch_size)
        ).all()
        return PassageEmbeddingBackfillSnapshot(
            candidates=candidates,
            items=tuple(
                PassageEmbeddingCandidate(
                    passage_id=passage_id,
                    document_id=document_id,
                    start_line=start_line,
                    source_digest=semantic_source_digest(content),
                    content=content,
                )
                for passage_id, document_id, start_line, content in rows
                if content.strip()
            ),
        )

    def apply_embeddings(
        self,
        *,
        records: tuple[PassageEmbeddingWrite, ...],
        model_revision: str,
    ) -> tuple[int, int]:
        indexed = 0
        stale = 0
        now = datetime.now(timezone.utc)
        for record in records:
            current = self._db.scalar(
                select(DocumentPassage.content).where(
                    DocumentPassage.id == record.passage_id,
                    DocumentPassage.document_id == record.document_id,
                    DocumentPassage.start_line == record.start_line,
                )
            )
            if (
                current is None
                or semantic_source_digest(current) != record.source_digest
            ):
                stale += 1
                continue
            self._db.execute(
                update(DocumentPassage)
                .where(DocumentPassage.id == record.passage_id)
                .values(
                    embedding=list(record.embedding),
                    embedding_model_revision=model_revision,
                    embedding_source_digest=record.source_digest,
                    embedded_at=now,
                )
            )
            indexed += 1
        return indexed, stale


__all__ = ["SqlPassageBackfill"]
