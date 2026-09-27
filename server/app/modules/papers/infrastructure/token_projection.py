"""Atomic, content-fenced adoption of complete token search projections."""

import hashlib
from uuid import UUID

from scholens_ai.token_projection import TokenProjection
from sqlalchemy import and_, delete, exists, insert, select, union_all
from sqlalchemy.sql.selectable import Subquery
from sqlalchemy.orm import Session

from app.modules.papers.infrastructure.models import (
    Document,
    DocumentPassage,
    DocumentTokenPassage,
    DocumentTokenProjection,
)


def searchable_passages(*, model_revision: str) -> Subquery:
    """Read one complete projection per document without reviving stale windows.

    Authorization is applied by the owning search query before ranking. Once a
    document has adopted this revision, a changed source has no semantic body
    until its replacement commits; old line windows must not mask that gap.
    """
    adopted = exists(
        select(DocumentTokenProjection.document_id).where(
            DocumentTokenProjection.document_id == DocumentPassage.document_id,
            DocumentTokenProjection.model_revision == model_revision,
        )
    )
    legacy = select(
        DocumentPassage.document_id,
        DocumentPassage.start_line,
        DocumentPassage.end_line,
        DocumentPassage.content,
        DocumentPassage.ts_vector,
        DocumentPassage.embedding,
        DocumentPassage.embedding_model_revision,
        DocumentPassage.id.label("sort_key"),
    ).where(~adopted)
    current = (
        select(
            DocumentTokenPassage.document_id,
            DocumentTokenPassage.start_line,
            DocumentTokenPassage.end_line,
            DocumentTokenPassage.content,
            DocumentTokenPassage.ts_vector,
            DocumentTokenPassage.embedding,
            DocumentTokenPassage.model_revision.label("embedding_model_revision"),
            DocumentTokenPassage.ordinal.label("sort_key"),
        )
        .join(
            DocumentTokenProjection,
            and_(
                DocumentTokenProjection.document_id == DocumentTokenPassage.document_id,
                DocumentTokenProjection.model_revision
                == DocumentTokenPassage.model_revision,
            ),
        )
        .join(Document, Document.id == DocumentTokenPassage.document_id)
        .where(
            DocumentTokenProjection.model_revision == model_revision,
            DocumentTokenProjection.content_digest == Document.content_digest,
        )
    )
    return union_all(legacy, current).subquery("searchable_passages")


class TokenProjectionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def adopt(self, *, document_id: UUID, projection: TokenProjection) -> bool:
        document = self._db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None or document.raw_content is None:
            return False
        # Old rows may have no digest until the bounded backfill or first write.
        # Validation against canonical text also fences those N-1 rows.
        if document.content_digest not in (None, projection.content_digest):
            return False
        try:
            passages = projection.validated_passages(document.raw_content)
        except ValueError:
            # Corrupt same-source output must retry/fail, never become complete.
            if (
                hashlib.sha256(document.raw_content.encode()).hexdigest()
                != projection.content_digest
            ):
                return False
            raise
        document.content_digest = projection.content_digest
        self._db.execute(
            delete(DocumentTokenProjection).where(
                DocumentTokenProjection.document_id == document_id,
                DocumentTokenProjection.model_revision == projection.model_revision,
            )
        )
        self._db.add(
            DocumentTokenProjection(
                document_id=document_id,
                model_revision=projection.model_revision,
                content_digest=projection.content_digest,
                chunk_revision=projection.chunk_revision,
                passage_count=len(passages),
            )
        )
        self._db.flush()
        # Keep driver parameter buffers bounded. All batches and the head remain
        # in the caller's transaction; readers see the old or complete new index.
        for offset in range(0, len(passages), 128):
            rows = []
            for passage in passages[offset : offset + 128]:
                rows.append(
                    {
                        "ordinal": passage.ordinal,
                        "start_offset": passage.start_offset,
                        "end_offset": passage.end_offset,
                        "start_line": passage.start_line,
                        "end_line": passage.end_line,
                        "token_count": passage.token_count,
                        "content": passage.content,
                        "source_digest": passage.source_digest,
                        "embedding": list(passage.embedding),
                        "document_id": document_id,
                        "model_revision": projection.model_revision,
                    }
                )
            self._db.execute(insert(DocumentTokenPassage), rows)
        return True
