from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.papers.infrastructure.details import SqlAlchemyPaperDetails
from app.shared.domain.enums import DocumentProcessingStatus
from sqlalchemy.orm import Session
from tests.test_mcp_transport import _actor


def test_paper_resource_metadata_uses_only_bounded_scalar_projection() -> None:
    document_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    db = MagicMock(spec=Session)
    db.execute.return_value.one_or_none.return_value = SimpleNamespace(
        id=document_id,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=123,
        title="bounded title",
        abstract="bounded abstract",
        doi="10.1000/example",
        journal="Journal",
        publisher="Publisher",
        summary="bounded summary",
        publish_date=None,
        processing_status=DocumentProcessingStatus.COMPLETED.value,
        parser_quality="full",
        parser_warning_code=None,
        created_at=now,
        updated_at=now,
    )

    preview = SqlAlchemyPaperDetails(db).get_resource_preview(
        actor=_actor(),
        document_id=document_id,
    )

    assert preview is not None
    assert preview.content_truncated is True
    assert preview.document.document_id == document_id
    assert preview.document.authors is None
    assert preview.document.summary_citations is None
    statement = db.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "original_filename",
        "mime_type",
        "size_bytes",
        "title",
        "abstract",
        "doi",
        "journal",
        "publisher",
        "summary",
        "publish_date",
        "processing_status",
        "parser_quality",
        "parser_warning_code",
        "created_at",
        "updated_at",
    )
    assert all(
        column.key
        not in {
            "authors",
            "institutions",
            "keywords",
            "summary_citations",
            "starter_questions",
            "raw_content",
        }
        for column in statement.selected_columns
    )
