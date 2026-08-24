"""SQLAlchemy adapter for canonical paper metadata."""

from typing import Any
from uuid import UUID

from app.modules.papers.application.contracts.documents import DocumentResponse
from app.modules.papers.application.details import (
    PaperDetailsResourcePreview,
    PaperDetailsRevision,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.document_loading import DOCUMENT_RESPONSE_COLUMNS
from app.modules.papers.infrastructure.library_gateway import document_response
from app.modules.papers.infrastructure.metadata_size import (
    document_json_utf8_upper_bound,
)
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session


def _bounded_text(column: object, length: int) -> Any:
    return func.left(cast(column, Text), length)


class SqlAlchemyPaperDetails:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsRevision | None:
        row = self._db.execute(
            select(Document.id, Document.updated_at).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        return PaperDetailsRevision(
            document_id=row.id,
            revision=row.updated_at.isoformat(),
        )

    def get_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsRevision | None:
        row = self._db.execute(
            select(
                Document.id,
                Document.updated_at,
                document_json_utf8_upper_bound().label("durable_json_utf8_upper_bound"),
            ).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        return PaperDetailsRevision(
            document_id=row.id,
            revision=row.updated_at.isoformat(),
            durable_json_utf8_upper_bound=int(row.durable_json_utf8_upper_bound),
        )

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> DocumentResponse | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
            document_columns=DOCUMENT_RESPONSE_COLUMNS,
        )
        return document_response(document) if document is not None else None

    def get_resource_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsResourcePreview | None:
        """Project bounded scalar metadata without hydrating unbounded columns."""

        row = self._db.execute(
            select(
                Document.id,
                Document.original_filename,
                Document.mime_type,
                Document.size_bytes,
                _bounded_text(Document.title, 512).label("title"),
                _bounded_text(Document.abstract, 1_024).label("abstract"),
                _bounded_text(Document.doi, 512).label("doi"),
                _bounded_text(Document.journal, 512).label("journal"),
                _bounded_text(Document.publisher, 512).label("publisher"),
                _bounded_text(Document.summary, 1_024).label("summary"),
                Document.publish_date,
                Document.processing_status,
                _bounded_text(Document.parser_quality, 128).label("parser_quality"),
                _bounded_text(Document.parser_warning_code, 128).label(
                    "parser_warning_code"
                ),
                Document.created_at,
                Document.updated_at,
            ).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        return PaperDetailsResourcePreview(
            document=DocumentResponse(
                document_id=row.id,
                original_filename=row.original_filename,
                mime_type=row.mime_type,
                size_bytes=row.size_bytes,
                title=row.title,
                authors=None,
                abstract=row.abstract,
                institutions=None,
                keywords=None,
                doi=row.doi,
                journal=row.journal,
                publisher=row.publisher,
                publish_date=row.publish_date,
                summary=row.summary,
                summary_citations=None,
                starter_questions=None,
                processing_status=row.processing_status,
                parser_quality=row.parser_quality,
                parser_warning_code=row.parser_warning_code,
                created_at=row.created_at,
                updated_at=row.updated_at,
            ),
            content_truncated=True,
        )
