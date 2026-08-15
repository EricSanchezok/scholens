"""PostgreSQL passage-index maintenance adapter."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.papers.application.maintenance import PassageBackfillResult
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

        indexed_documents = 0
        indexed_passages = 0
        self._db.execute(
            text(
                "ALTER TABLE scholens.document_passages "
                "DISABLE TRIGGER document_passages_tsvectorupdate"
            )
        )
        while True:
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
            if not rows:
                break
            passages: list[dict[str, object]] = []
            for document_id, raw_content in rows:
                passages.extend(
                    {"document_id": document_id, **passage}
                    for passage in document_search_repository.build_passages(
                        raw_content
                    )
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
            indexed_documents += len(rows)
            indexed_passages += len(passages)

        self._db.execute(
            text(
                """
                UPDATE scholens.document_passages
                SET ts_vector = to_tsvector(
                    'pg_catalog.english', coalesce(content, '')
                )
                WHERE ts_vector IS NULL
                """
            )
        )
        self._db.execute(
            text(
                "ALTER TABLE scholens.document_passages "
                "ENABLE TRIGGER document_passages_tsvectorupdate"
            )
        )
        return PassageBackfillResult(
            candidates=candidates,
            indexed_documents=indexed_documents,
            indexed_passages=indexed_passages,
        )


__all__ = ["SqlPassageBackfill"]
