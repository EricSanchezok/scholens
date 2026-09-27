"""Bounded source snapshots and atomic adoption of the canonical token projection."""

from uuid import UUID

from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    TOKEN_PASSAGE_REVISION,
    TokenProjection,
)
from scholens_job_contracts import MAX_PDF_CALLBACK_RAW_CONTENT_BYTES
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.papers.application.token_maintenance import (
    TokenIndexRepairPage,
    TokenIndexSource,
)
from app.modules.papers.infrastructure.models import Document, DocumentTokenProjection
from app.modules.papers.infrastructure.token_projection import TokenProjectionRepository


class SqlTokenIndexRepair:
    def __init__(self, db: Session) -> None:
        self._db = db

    def candidates(
        self, *, batch_size: int, after_document_id: UUID | None
    ) -> TokenIndexRepairPage:
        if not 1 <= batch_size <= 25:
            raise ValueError("token_index_repair_batch_invalid")
        statement = select(
            Document.id,
            Document.content_digest,
            func.octet_length(Document.raw_content).label("size"),
            DocumentTokenProjection.content_digest.label("indexed_digest"),
            DocumentTokenProjection.chunk_revision,
        ).outerjoin(
            DocumentTokenProjection,
            (DocumentTokenProjection.document_id == Document.id)
            & (DocumentTokenProjection.model_revision == EMBEDDING_MODEL_REVISION),
        )
        if after_document_id:
            statement = statement.where(Document.id > after_document_id)
        rows = self._db.execute(
            statement.order_by(Document.id).limit(batch_size + 1)
        ).all()
        page, candidates, skipped = rows[:batch_size], [], 0
        for row in page:
            if (row.size or 0) > MAX_PDF_CALLBACK_RAW_CONTENT_BYTES:
                skipped += 1
            elif row.size and (
                not row.content_digest
                or row.indexed_digest != row.content_digest
                or row.chunk_revision != TOKEN_PASSAGE_REVISION
            ):
                candidates.append(row.id)
        return TokenIndexRepairPage(
            len(page),
            tuple(candidates),
            skipped,
            page[-1].id if len(rows) > batch_size else None,
        )

    def source(self, *, document_id: UUID) -> TokenIndexSource | None:
        # Never hydrate a page of bodies or hold the connection during inference.
        body = self._db.scalar(
            select(Document.raw_content).where(
                Document.id == document_id,
                func.octet_length(Document.raw_content)
                <= MAX_PDF_CALLBACK_RAW_CONTENT_BYTES,
            )
        )
        return TokenIndexSource(document_id, body) if body else None

    def apply_projection(
        self, *, document_id: UUID, projection: TokenProjection
    ) -> bool:
        if projection.model_revision != EMBEDDING_MODEL_REVISION:
            raise ValueError("token_index_repair_model_invalid")
        return TokenProjectionRepository(self._db).adopt(
            document_id=document_id, projection=projection
        )
