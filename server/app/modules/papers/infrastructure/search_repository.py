"""Passage indexing and topic queries for canonical Documents."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from scholens_ai import build_document_passages, semantic_source_digest

from app.helpers.postgres import sanitize_for_postgres
from app.database.models import DocumentPassage, PaperTag
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class PassageInsert(TypedDict):
    start_line: int
    end_line: int
    content: str


class DocumentSearchRepository:
    @staticmethod
    def build_passages(
        raw_content: str,
        *,
        window: int = 5,
        stride: int = 3,
    ) -> list[PassageInsert]:
        return [
            {
                "start_line": passage.start_line,
                "end_line": passage.end_line,
                "content": passage.content,
            }
            for passage in build_document_passages(
                raw_content,
                window=window,
                stride=stride,
            )
        ]

    def replace_passage_index(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        raw_content: str,
        window: int = 5,
        stride: int = 3,
        embeddings: dict[str, list[float]] | None = None,
        embedding_model_revision: str | None = None,
    ) -> None:
        sanitized = sanitize_for_postgres(raw_content)
        if sanitized != raw_content:
            logger.warning(
                "paper_search.passages.null_characters_sanitized",
                extra={"document_id": str(document_id)},
            )
        db.execute(
            delete(DocumentPassage).where(DocumentPassage.document_id == document_id)
        )
        passages = self.build_passages(
            sanitized,
            window=window,
            stride=stride,
        )
        if passages:
            expected_embedding_digests = {
                semantic_source_digest(passage["content"])
                for passage in passages
                if passage["content"].strip()
            }
            valid_embeddings = embeddings
            if embeddings is not None and (
                embedding_model_revision is None
                or set(embeddings) != expected_embedding_digests
            ):
                logger.warning(
                    "paper_search.passages.embedding_artifact_content_mismatch",
                    extra={"document_id": str(document_id)},
                )
                valid_embeddings = None
            rows: list[dict[str, object]] = []
            for passage in passages:
                digest = semantic_source_digest(passage["content"])
                embedding = (valid_embeddings or {}).get(digest)
                rows.append(
                    {
                        "document_id": document_id,
                        **passage,
                        "embedding": embedding,
                        "embedding_model_revision": (
                            embedding_model_revision if embedding is not None else None
                        ),
                        "embedding_source_digest": (
                            digest if embedding is not None else None
                        ),
                        "embedded_at": (
                            datetime.now(timezone.utc)
                            if embedding is not None
                            else None
                        ),
                    }
                )
            db.execute(insert(DocumentPassage), rows)
        db.flush()

    def list_topics(self, db: Session, *, user_id: int) -> list[str]:
        names = db.scalars(
            select(PaperTag.name)
            .join(PaperTag.library_papers)
            .where(PaperTag.user_id == user_id)
            .distinct()
        ).all()
        return [name.strip() for name in names if name and name.strip()]


document_search_repository = DocumentSearchRepository()
