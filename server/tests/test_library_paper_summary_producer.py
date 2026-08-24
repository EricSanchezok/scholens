from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.modules.papers.application.contracts.documents import LibraryPaperSort
from app.modules.papers.application.library import LibraryPageDirection
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
)
from app.shared.domain.enums import DocumentProcessingStatus, PaperStatus


def _gateway(db: Session) -> SqlAlchemyPaperLibraryGateway:
    return SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )


def test_library_summary_selects_bounded_scalars_before_model_construction() -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    entry_id = uuid4()
    document_id = uuid4()
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            library_entry_id=entry_id,
            user_id=7,
            status=PaperStatus.reading,
            last_accessed_at=now,
            override_title="Personal title",
            override_abstract=None,
            override_doi=None,
            override_journal=None,
            override_publisher=None,
            override_publish_date=None,
            is_public=False,
            entry_created_at=now,
            entry_updated_at=now,
            document_id=document_id,
            original_filename="paper.pdf",
            mime_type="application/pdf",
            size_bytes=42,
            title="Bounded title",
            abstract="\\" * 512,
            doi=None,
            journal=None,
            publisher=None,
            publish_date=None,
            summary=None,
            processing_status=DocumentProcessingStatus.COMPLETED,
            parser_quality=None,
            parser_warning_code=None,
            document_created_at=now,
            document_updated_at=now,
            content_truncated=False,
        )
    ]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.return_value = result

    page = _gateway(db).list_summaries(
        user_id=7,
        query="bounded",
        tag_ids=(uuid4(),),
        statuses=(PaperStatus.reading,),
        sort=LibraryPaperSort.TITLE_ASC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    item = page.items[0]
    assert item.entry_type == "paper"
    assert item.document.document_id == document_id
    assert item.document.authors is None
    assert item.document.institutions is None
    assert item.document.keywords is None
    assert item.document.summary_citations is None
    assert item.metadata_overrides.authors is None
    assert item.tags == []
    assert page.content_truncated is True
    assert len(item.document.abstract or "") < 512

    statement = db.execute.call_args.args[0]
    selected = {column.key for column in statement.selected_columns}
    assert selected.isdisjoint(
        {
            "authors",
            "institutions",
            "keywords",
            "summary_citations",
            "starter_questions",
            "metadata_overrides",
            "tags",
            "raw_content",
            "s3_object_key",
            "preview_s3_key",
        }
    )
    assert {
        "library_entry_id",
        "override_title",
        "document_id",
        "abstract",
        "content_truncated",
    } <= selected
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(scholens.library_papers.metadata_overrides" in sql
    assert "left(CAST(scholens.documents.abstract AS TEXT)" in sql
    assert "scholens.library_paper_tags" in sql
    assert "scholens.library_papers.status IN" in sql


def test_library_summary_marks_omitted_historical_collections_without_loading_them() -> (
    None
):
    now = datetime(2026, 8, 24, tzinfo=UTC)
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            library_entry_id=uuid4(),
            user_id=7,
            status=PaperStatus.reading,
            last_accessed_at=now,
            override_title=None,
            override_abstract=None,
            override_doi=None,
            override_journal=None,
            override_publisher=None,
            override_publish_date="not-a-date",
            is_public=False,
            entry_created_at=now,
            entry_updated_at=now,
            document_id=uuid4(),
            original_filename="paper.pdf",
            mime_type="application/pdf",
            size_bytes=42,
            title="Title",
            abstract=None,
            doi=None,
            journal=None,
            publisher=None,
            publish_date=None,
            summary=None,
            processing_status=DocumentProcessingStatus.COMPLETED,
            parser_quality=None,
            parser_warning_code=None,
            document_created_at=now,
            document_updated_at=now,
            content_truncated=True,
        )
    ]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.return_value = result

    page = _gateway(db).list_summaries(
        user_id=7,
        query=None,
        tag_ids=(),
        statuses=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert page.content_truncated is True
    assert page.items[0].metadata_overrides.publish_date is None
    statement = db.execute.call_args.args[0]
    override_date_column = next(
        column
        for column in statement.selected_columns
        if column.key == "override_publish_date"
    )
    override_date_sql = str(override_date_column.compile(dialect=postgresql.dialect()))
    assert "left(" in override_date_sql
    assert "metadata_overrides" in override_date_sql
