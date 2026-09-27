"""Bounded metadata snapshots and compare-before-write vector adoption.

Inference belongs outside the database transaction; callers may be durable
Jobs or the private, keyset-paged repair command. Neither scans all Documents.
"""

from datetime import datetime, timezone
import math
from uuid import UUID
from typing import Any

from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    semantic_source_digest,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.papers.application.maintenance import (
    SearchEmbeddingCandidate,
    SearchEmbeddingSnapshot,
    SearchEmbeddingWrite,
)
from app.modules.papers.infrastructure.models import Document, DocumentSearchEmbedding


# Python str.strip whitespace, including Unicode separators, for the existing
# semantic_document_text contract. Trimming before the final prefix is essential
# for legacy metadata with long leading whitespace. Only 24k chars cross SQL.
_SEMANTIC_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f\x85 \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def _metadata_columns() -> tuple[Any, ...]:
    sections = (
        Document.title,
        func.array_to_string(Document.keywords, " · "),
        Document.summary,
        Document.abstract,
    )
    semantic_text = func.left(
        func.concat_ws(
            "\n\n",
            *(
                func.nullif(
                    func.btrim(func.coalesce(section, ""), _SEMANTIC_WHITESPACE), ""
                )
                for section in sections
            ),
        ),
        24000,
    )
    return (Document.id, Document.search_revision, semantic_text.label("semantic_text"))


def _semantic_text(row: Any) -> str:
    return str(row.semantic_text)


class SqlSearchEmbeddingBackfill:
    def __init__(self, db: Session) -> None:
        self._db = db

    def candidates(
        self, *, batch_size: int, after_document_id: UUID | None = None
    ) -> SearchEmbeddingSnapshot:
        if not 1 <= batch_size <= 1000:
            raise ValueError("metadata_scan_batch_invalid")
        statement = select(
            *_metadata_columns(),
            DocumentSearchEmbedding.source_digest,
            DocumentSearchEmbedding.source_revision,
        ).outerjoin(
            DocumentSearchEmbedding,
            (DocumentSearchEmbedding.document_id == Document.id)
            & (DocumentSearchEmbedding.model_revision == EMBEDDING_MODEL_REVISION),
        )
        if after_document_id:
            statement = statement.where(Document.id > after_document_id)
        rows = self._db.execute(
            statement.order_by(Document.id).limit(batch_size + 1)
        ).all()
        page = rows[:batch_size]
        candidates = []
        for row in page:
            text = _semantic_text(row)
            digest = semantic_source_digest(text)
            if text and (
                row.source_digest != digest
                or (row.source_revision or 0) != (row.search_revision or 0)
            ):
                candidates.append(
                    SearchEmbeddingCandidate(
                        document_id=row.id, source_digest=digest, content=text
                    )
                )
        return SearchEmbeddingSnapshot(
            scanned=len(page),
            items=tuple(candidates),
            next_cursor=page[-1].id if len(rows) > batch_size else None,
        )

    def apply_embeddings(
        self, *, records: tuple[SearchEmbeddingWrite, ...], model_revision: str
    ) -> tuple[int, int]:
        if model_revision != EMBEDDING_MODEL_REVISION or len(records) > 1000:
            raise ValueError("metadata_projection_revision_invalid")
        indexed, stale = 0, 0
        # Stable locking order also protects concurrent repair invocations.
        for record in sorted(records, key=lambda item: item.document_id):
            if len(record.embedding) != 384 or not all(
                math.isfinite(value) for value in record.embedding
            ):
                raise ValueError("metadata_projection_vector_invalid")
            row = self._db.execute(
                select(*_metadata_columns())
                .where(Document.id == record.document_id)
                .with_for_update()
            ).one_or_none()
            if (
                row is None
                or semantic_source_digest(_semantic_text(row)) != record.source_digest
            ):
                stale += 1
                continue
            statement = insert(DocumentSearchEmbedding).values(
                document_id=record.document_id,
                model_revision=model_revision,
                source_digest=record.source_digest,
                embedding=list(record.embedding),
                source_revision=row.search_revision or 0,
                indexed_at=datetime.now(timezone.utc),
            )
            self._db.execute(
                statement.on_conflict_do_update(
                    index_elements=(
                        DocumentSearchEmbedding.document_id,
                        DocumentSearchEmbedding.model_revision,
                    ),
                    set_={
                        "source_digest": statement.excluded.source_digest,
                        "embedding": statement.excluded.embedding,
                        "source_revision": statement.excluded.source_revision,
                        "indexed_at": statement.excluded.indexed_at,
                    },
                )
            )
            indexed += 1
        return indexed, stale


__all__ = ["SqlSearchEmbeddingBackfill"]
