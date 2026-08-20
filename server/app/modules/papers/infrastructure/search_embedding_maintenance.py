"""Local semantic-search projection maintenance."""

from __future__ import annotations

from datetime import datetime, timezone

from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    semantic_document_text,
    semantic_source_digest,
    try_local_embedder,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.papers.application.maintenance import (
    SearchEmbeddingBackfillResult,
)
from app.modules.papers.infrastructure.models import (
    Document,
    DocumentSearchEmbedding,
)


class SqlSearchEmbeddingBackfill:
    def __init__(self, db: Session) -> None:
        self._db = db

    def backfill(
        self, *, batch_size: int, apply: bool
    ) -> SearchEmbeddingBackfillResult:
        rows = self._db.execute(
            select(
                Document.id,
                Document.title,
                Document.keywords,
                Document.summary,
                Document.abstract,
                DocumentSearchEmbedding.source_digest,
            )
            .outerjoin(
                DocumentSearchEmbedding,
                (DocumentSearchEmbedding.document_id == Document.id)
                & (DocumentSearchEmbedding.model_revision == EMBEDDING_MODEL_REVISION),
            )
            .order_by(Document.id)
        ).all()
        candidates: list[tuple[object, str, str]] = []
        for document_id, title, keywords, summary, abstract, stored_digest in rows:
            semantic_text = semantic_document_text(
                title=title,
                keywords=keywords,
                summary=summary,
                abstract=abstract,
            )
            if not semantic_text:
                continue
            source_digest = semantic_source_digest(semantic_text)
            if stored_digest != source_digest:
                candidates.append((document_id, semantic_text, source_digest))

        if not apply or not candidates:
            return SearchEmbeddingBackfillResult(
                candidates=len(candidates),
                indexed_documents=0,
            )

        selected = candidates[:batch_size]
        embedder = try_local_embedder()
        if embedder is None:
            raise RuntimeError("local embedding model is not configured")
        embeddings = embedder.embed_passages([item[1] for item in selected])
        now = datetime.now(timezone.utc)
        for (document_id, _semantic_text, source_digest), embedding in zip(
            selected, embeddings, strict=True
        ):
            statement = insert(DocumentSearchEmbedding).values(
                document_id=document_id,
                model_revision=EMBEDDING_MODEL_REVISION,
                source_digest=source_digest,
                embedding=embedding,
                indexed_at=now,
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
                        "indexed_at": now,
                    },
                )
            )
        return SearchEmbeddingBackfillResult(
            candidates=len(candidates),
            indexed_documents=len(selected),
        )


__all__ = ["SqlSearchEmbeddingBackfill"]
