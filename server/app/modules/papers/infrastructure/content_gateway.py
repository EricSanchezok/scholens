"""SQLAlchemy adapter for the paper-content application port."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.modules.papers.application.content import (
    AccessiblePaperContentPreview,
    AccessiblePaperContent,
    PaperContentRevision,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_PAPER_CONTENT_COLUMNS,
    DOCUMENT_PAPER_PAGING_COLUMNS,
)
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor


class SqlAlchemyPaperContentGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperContentRevision | None:
        """Authorize and return a row revision without selecting large text fields."""

        row = self._db.execute(
            select(Document.id, Document.updated_at).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        return PaperContentRevision(
            document_id=row.id,
            revision=row.updated_at.isoformat(),
        )

    def get_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperContentRevision | None:
        """Calculate the conservative retained bound only on a cache miss."""

        row = self._db.execute(
            select(
                Document.id,
                Document.updated_at,
                func.coalesce(
                    func.char_length(cast(Document.raw_content, Text)), 0
                ).label("raw_character_count"),
                func.coalesce(func.char_length(cast(Document.title, Text)), 0).label(
                    "title_character_count"
                ),
            ).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        return PaperContentRevision(
            document_id=row.id,
            revision=row.updated_at.isoformat(),
            retained_size_upper_bound=_retained_size_upper_bound(
                raw_character_count=int(row.raw_character_count),
                title_character_count=int(row.title_character_count),
            ),
        )

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
            document_columns=DOCUMENT_PAPER_CONTENT_COLUMNS,
        )
        if document is None:
            return None
        return AccessiblePaperContent(
            document_id=document.id,
            original_filename=document.original_filename,
            title=document.title,
            abstract=document.abstract,
            raw_content=document.raw_content,
            storage_key=document.s3_object_key,
            parser_markdown_storage_key=document.parser_markdown_s3_key,
            content_revision=document.updated_at.isoformat(),
        )

    def get_snapshot(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
            document_columns=DOCUMENT_PAPER_PAGING_COLUMNS,
        )
        if document is None:
            return None
        return AccessiblePaperContent(
            document_id=document.id,
            original_filename="",
            title=document.title,
            abstract=None,
            raw_content=document.raw_content,
            storage_key="",
            parser_markdown_storage_key=None,
            content_revision=document.updated_at.isoformat(),
        )

    def get_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        max_characters: int,
    ) -> AccessiblePaperContentPreview | None:
        """Select only a fixed-size text prefix and scalar full-text facts."""

        raw_text = cast(Document.raw_content, Text)
        raw_character_count = func.coalesce(func.char_length(raw_text), 0)
        line_break_pattern = "\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]"
        line_break_count = func.regexp_count(raw_text, line_break_pattern)
        ends_with_line_break = raw_text.op("~")(f"({line_break_pattern})$")
        total_lines = case(
            (
                or_(Document.raw_content.is_(None), raw_character_count == 0),
                0,
            ),
            else_=(1 + line_break_count - case((ends_with_line_break, 1), else_=0)),
        )
        row = self._db.execute(
            select(
                Document.id,
                Document.updated_at,
                func.left(raw_text, max_characters).label("content_prefix"),
                raw_character_count.label("raw_character_count"),
                total_lines.label("total_lines"),
            ).where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
        ).one_or_none()
        if row is None:
            return None
        content = row.content_prefix
        return AccessiblePaperContentPreview(
            document_id=row.id,
            revision=row.updated_at.isoformat(),
            content=content,
            total_lines=int(row.total_lines),
            truncated=(
                content is not None and int(row.raw_character_count) > len(content)
            ),
        )


def _retained_size_upper_bound(
    *,
    raw_character_count: int,
    title_character_count: int,
) -> int:
    """Conservatively bound the CPython strings and sparse line index.

    A Python Unicode code point occupies at most four bytes in its canonical
    representation. In the hostile all-separator case the pager retains one
    integer checkpoint per 256 lines; 64 bytes per checkpoint safely covers
    the tuple slot and integer object. The fixed allowance covers object,
    digest, revision, and optional-string headers.
    """

    checkpoint_count = raw_character_count // 256 + 2
    return (
        4 * (raw_character_count + title_character_count)
        + 64 * checkpoint_count
        + 4_096
    )
