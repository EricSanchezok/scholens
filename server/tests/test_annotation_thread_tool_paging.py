from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.bootstrap.adapters.annotation_summary_catalog import (
    SqlAlchemyAnnotationSummaryCatalog,
)
from app.bootstrap.adapters.research_access import research_item_policy
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import AnnotationComment, AnnotationThread, ResearchItem
from app.modules.research.application.contracts import (
    AnnotationThreadCapabilities,
    AnnotationThreadSummaryResponse,
    ProjectResearchAudience,
    ResearchCreatorResponse,
)
from app.modules.research.application.items import (
    AnnotationThreadSummaryKeyset,
    AnnotationThreadSummaryPage,
)
from app.modules.research.application.positions import PdfTextPosition, PdfTextRect
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError
from app.shared.domain.enums import (
    AnnotationColor,
    AnnotationThreadMode,
    AnnotationThreadStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from app.tooling import DEFAULT_TOOL_OUTPUT_BYTES, serialize_tool_success
from app.tooling.annotation_summary_projection import (
    ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
    ANNOTATION_SUMMARY_MAX_PAGE_ITEMS,
    ANNOTATION_SUMMARY_QUOTE_JSON_BYTES,
    project_annotation_summary,
)
from app.tooling.contracts import ToolExecutionContext
from app.tooling.workspace_contracts import ListAnnotationThreadsInput, ThreadListOutput
from app.tooling.workspace_handlers import WorkspaceToolHandlers
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def _actor(*, actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id,
        email=f"researcher-{actor_id}@example.com",
        status="active",
        email_verified=True,
    )


def _context(*, actor_id: int = 7) -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(actor_id=actor_id),
        operation=operation,
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="annotation-summary-page-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="annotation-summary-test-secret",
    )


def _keyset(item_id: UUID, created_at: datetime) -> AnnotationThreadSummaryKeyset:
    return AnnotationThreadSummaryKeyset(
        page_number=2,
        anchor_y=0.25,
        anchor_x=0.5,
        start_offset=None,
        end_offset=None,
        created_at=created_at,
        item_id=item_id,
    )


def _summary(
    *,
    document_id: UUID,
    quote_text: str = "Evidence",
    display_name: str = "Researcher",
) -> AnnotationThreadSummaryResponse:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    rects = [PdfTextRect(x=0.1, y=0.2, width=0.3, height=0.1) for _ in range(200)]
    return AnnotationThreadSummaryResponse(
        id=uuid4(),
        audience=ProjectResearchAudience(project_id=uuid4()),
        target_document_id=document_id,
        created_by=ResearchCreatorResponse(id=7, display_name=display_name),
        created_at=now,
        quote_text=quote_text,
        position=PdfTextPosition(page_number=2, rects=rects),
        color=AnnotationColor.YELLOW,
        role="assistant",
        mode=AnnotationThreadMode.DISCUSSION,
        comment_count=1_000_000,
        last_activity_at=now,
        status=AnnotationThreadStatus.RESOLVED,
        resolved_by=ResearchCreatorResponse(id=8, display_name=display_name),
        resolved_at=now,
        capabilities=AnnotationThreadCapabilities(
            reply=False,
            recolor=True,
            resolve=False,
            reopen=True,
            delete=False,
        ),
        comments=[],
    )


class _PoisonFullPosition:
    def __getitem__(self, _key: object) -> object:
        raise AssertionError("the full annotation position must not be consumed")

    def __iter__(self):
        raise AssertionError("the full annotation position must not be consumed")

    def __str__(self) -> str:
        raise AssertionError("the full annotation position must not be consumed")


def _bounded_row(
    *,
    document_id: UUID,
    project_id: UUID | None,
    position_kind: str,
    hostile: str,
) -> dict[str, object]:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    is_project = project_id is not None
    return {
        "item_id": uuid4(),
        "audience_type": (
            ResearchAudienceType.PROJECT.value
            if is_project
            else ResearchAudienceType.PERSONAL.value
        ),
        "audience_project_id": project_id,
        "target_document_id": document_id,
        "created_by_id": 8 if is_project else 7,
        "creator_display_name": hostile,
        "created_at": now,
        "quote_text": hostile,
        "position_kind": position_kind,
        "page_number": 2,
        "anchor_y": 0.2 if position_kind == "pdf_text" else None,
        "anchor_x": 0.1 if position_kind == "pdf_text" else None,
        "rect_width": 0.3 if position_kind == "pdf_text" else None,
        "rect_height": 0.1 if position_kind == "pdf_text" else None,
        "start_offset": 10 if position_kind == "parsed_text" else None,
        "end_offset": 20 if position_kind == "parsed_text" else None,
        "color": AnnotationColor.YELLOW.value,
        "role": "assistant",
        "status": AnnotationThreadStatus.OPEN.value,
        "resolved_by_id": None,
        "resolver_display_name": None,
        "resolved_at": None,
        "comment_count": 2 if is_project else 0,
        "last_activity_at": now,
        "has_foreign_replies": is_project,
        "position": _PoisonFullPosition(),
    }


def test_annotation_summary_repository_uses_limit_plus_one_keyset_sql() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = uuid4()
    db.execute.return_value.mappings.return_value.all.return_value = []
    after = _keyset(uuid4(), datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    page = SqlAlchemyAnnotationSummaryCatalog(db).list_page(
        document_id=uuid4(),
        user_id=7,
        project_id=None,
        audience=None,
        mode=None,
        status=AnnotationThreadStatus.OPEN,
        after=after,
        limit=2,
    )

    statement = db.execute.call_args.args[0]
    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    assert page == AnnotationThreadSummaryPage(items=[], next_keyset=None)
    assert "LIMIT 3" in sql
    assert ") > (0, 2, 0, 0.25, 0, 0.5, 1, 0, 1, 0," in sql
    assert "annotation_threads.page_number ASC NULLS LAST" in sql
    assert "research_items.*" not in sql.lower()
    assert not statement._with_options


def test_annotation_summary_catalog_projects_only_bounded_scalars() -> None:
    document_id = uuid4()
    project_id = uuid4()
    hostile = '\x00\\"中🙂' * 500
    rows = [
        _bounded_row(
            document_id=document_id,
            project_id=None,
            position_kind="pdf_text",
            hostile=hostile,
        ),
        _bounded_row(
            document_id=document_id,
            project_id=project_id,
            position_kind="parsed_text",
            hostile=hostile,
        ),
    ]
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [uuid4(), 1, uuid4()]
    db.scalars.side_effect = AssertionError(
        "the summary catalog must not hydrate full ORM rows"
    )
    db.execute.return_value.mappings.return_value.all.return_value = rows

    page = SqlAlchemyAnnotationSummaryCatalog(db).list_page(
        document_id=document_id,
        user_id=7,
        project_id=project_id,
        audience=None,
        mode=None,
        status=AnnotationThreadStatus.OPEN,
        after=None,
        limit=2,
    )

    assert len(page.items) == 2
    assert page.next_keyset is None
    personal, project = page.items
    assert personal.mode is AnnotationThreadMode.HIGHLIGHT
    assert personal.capabilities.model_dump() == {
        "reply": True,
        "recolor": True,
        "resolve": False,
        "reopen": False,
        "delete": True,
    }
    assert isinstance(personal.position, PdfTextPosition)
    assert len(personal.position.rects) == 1
    assert personal.position.segments is None
    assert project.mode is AnnotationThreadMode.DISCUSSION
    assert project.capabilities.model_dump() == {
        "reply": True,
        "recolor": False,
        "resolve": True,
        "reopen": False,
        "delete": False,
    }
    assert project.position is not None
    assert project.position.kind == "parsed_text"
    assert all(item.comments == [] for item in page.items)
    assert all(
        len(json.dumps(item.quote_text, ensure_ascii=False).encode("utf-8"))
        <= ANNOTATION_SUMMARY_QUOTE_JSON_BYTES
        for item in page.items
    )
    assert all(
        item.created_by.display_name is not None
        and len(
            json.dumps(
                item.created_by.display_name,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES
        for item in page.items
    )
    db.scalars.assert_not_called()

    document_access_statement = db.scalar.call_args_list[0].args[0]
    document_access_sql = str(
        document_access_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "documents.raw_content" not in document_access_sql
    assert "library_papers.metadata_overrides" not in document_access_sql

    access_statement = db.scalar.call_args_list[1].args[0]
    access_sql = str(
        access_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "projects.description" not in access_sql
    assert "project_collaborators.can_edit_project" in access_sql

    statement = db.execute.call_args.args[0]
    selected = {column.key for column in statement.selected_columns}
    sql = (
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        .lower()
        .replace("scholens.", "")
    )
    assert "position" not in selected
    assert {
        "position_kind",
        "page_number",
        "anchor_y",
        "anchor_x",
        "rect_width",
        "rect_height",
        "start_offset",
        "end_offset",
    } <= selected
    assert "research_items.*" not in sql
    assert "annotation_comments.content" not in sql
    assert "segments" not in sql
    assert "left(annotation_threads.quote_text, 256)" in sql
    assert "annotation_summary_resolver.display_name" in sql
    assert "annotation_summary_resolver.email" in sql
    assert "count(annotation_comments.id)" in sql
    assert "max(annotation_comments.updated_at)" in sql
    assert "exists (select" in sql
    assert sql.count("jsonb_typeof(") >= 5
    assert sql.count("as float)") >= 4
    assert "length(" in sql
    assert "[ee][+-]?[0-9]{1,2}" in sql
    assert "case when" in sql


def test_annotation_summary_catalog_degrades_hostile_positions_without_hydration() -> (
    None
):
    document_id = uuid4()
    hostile = "bounded"
    good_pdf = _bounded_row(
        document_id=document_id,
        project_id=None,
        position_kind="pdf_text",
        hostile=hostile,
    )
    good_parsed = _bounded_row(
        document_id=document_id,
        project_id=None,
        position_kind="parsed_text",
        hostile=hostile,
    )

    bad_positions: list[dict[str, object]] = []
    for updates in (
        {"anchor_x": None},
        {"anchor_x": ""},
        {"anchor_x": "NaN"},
        {"anchor_x": "Infinity"},
        {"anchor_x": {"nested": 0.1}},
        {"anchor_x": [0.1]},
        {"anchor_x": float("nan")},
        {"anchor_x": float("inf")},
        {"anchor_x": -0.1},
        {"anchor_x": 0.9, "rect_width": 0.2},
        {"rect_width": 0.0},
        {"page_number": None},
        {"position_kind": "unknown"},
        {"position_kind": None},
    ):
        row = _bounded_row(
            document_id=document_id,
            project_id=None,
            position_kind="pdf_text",
            hostile=hostile,
        )
        row.update(updates)
        bad_positions.append(row)
    for updates in (
        {"start_offset": None},
        {"start_offset": -1},
        {"start_offset": 20, "end_offset": 20},
        {"start_offset": 21, "end_offset": 20},
        {"page_number": 0},
    ):
        row = _bounded_row(
            document_id=document_id,
            project_id=None,
            position_kind="parsed_text",
            hostile=hostile,
        )
        row.update(updates)
        bad_positions.append(row)

    rows = [good_pdf, good_parsed, *bad_positions]
    db = MagicMock(spec=Session)
    db.scalar.return_value = uuid4()
    db.scalars.side_effect = AssertionError(
        "the summary catalog must not hydrate full ORM rows"
    )
    db.execute.return_value.mappings.return_value.all.return_value = rows

    page = SqlAlchemyAnnotationSummaryCatalog(db).list_page(
        document_id=document_id,
        user_id=7,
        project_id=None,
        audience=None,
        mode=None,
        status=AnnotationThreadStatus.OPEN,
        after=None,
        limit=len(rows),
    )

    assert isinstance(page.items[0].position, PdfTextPosition)
    assert page.items[1].position is not None
    assert page.items[1].position.kind == "parsed_text"
    assert all(item.position is None for item in page.items[2:])
    assert all(isinstance(row["position"], _PoisonFullPosition) for row in rows)
    db.scalars.assert_not_called()


def test_annotation_summary_scalar_row_preserves_resolved_capabilities() -> None:
    hostile = '\x00\\"中🙂' * 500
    row = _bounded_row(
        document_id=uuid4(),
        project_id=uuid4(),
        position_kind="parsed_text",
        hostile=hostile,
    )
    resolved_at = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    row.update(
        {
            "status": AnnotationThreadStatus.RESOLVED.value,
            "resolved_by_id": 9,
            "resolver_display_name": hostile,
            "resolved_at": resolved_at,
        }
    )

    summary = SqlAlchemyAnnotationSummaryCatalog._summary(
        row,
        user_id=7,
        can_edit_project=True,
    )

    assert summary.status is AnnotationThreadStatus.RESOLVED
    assert summary.resolved_at == resolved_at
    assert summary.resolved_by is not None
    assert summary.resolved_by.id == 9
    assert summary.resolved_by.display_name is not None
    assert (
        len(
            json.dumps(
                summary.resolved_by.display_name,
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES
    )
    assert summary.capabilities.model_dump() == {
        "reply": False,
        "recolor": False,
        "resolve": False,
        "reopen": True,
        "delete": False,
    }


def test_repository_summary_page_omits_comments_but_preserves_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    document_id = uuid4()
    item = ResearchItem(
        id=uuid4(),
        kind=ResearchItemKind.ANNOTATION_THREAD.value,
        created_by_id=7,
        audience_type=ResearchAudienceType.PERSONAL.value,
        target_document_id=document_id,
        created_at=now,
        updated_at=now,
    )
    item.annotation_thread = AnnotationThread(
        quote_text="Evidence",
        color=AnnotationColor.YELLOW.value,
        role="user",
        status=AnnotationThreadStatus.OPEN.value,
    )
    item.annotation_thread.comments = [
        AnnotationComment(
            id=uuid4(),
            thread_id=item.id,
            content="Complete discussion content",
            role="user",
            created_by_id=7,
            created_at=now,
            updated_at=now,
        )
    ]
    monkeypatch.setattr(
        research_item_policy,
        "require_visible",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_audience_access=True,
            can_manage=True,
            can_resolve=False,
        ),
    )

    summary = research_repository.serialize_annotation_summary(
        MagicMock(spec=Session),
        item=item,
        user_id=7,
        comment_count=1,
        last_activity_at=now,
        has_foreign_replies=False,
        include_comments=False,
    )

    assert summary.comment_count == 1
    assert summary.comments == []


def test_annotation_cursor_rejects_tampering_and_actor_changes() -> None:
    document_id = uuid4()
    summary = _summary(document_id=document_id)
    keyset = _keyset(summary.id, summary.created_at)
    capabilities = MagicMock()
    capabilities.research_items.list_annotation_thread_summaries_page.return_value = (
        AnnotationThreadSummaryPage(items=[summary], next_keyset=keyset)
    )
    handler = _handler()
    request = ListAnnotationThreadsInput(document_id=document_id, limit=1)
    first = ThreadListOutput.model_validate(
        handler.list_annotation_threads(capabilities, _context(), request).payload
    )
    assert first.next_cursor is not None

    replacement = "A" if first.next_cursor[0] != "A" else "B"
    tampered = replacement + first.next_cursor[1:]
    with pytest.raises(AppError) as exc_info:
        handler.list_annotation_threads(
            capabilities,
            _context(),
            request.model_copy(update={"cursor": tampered}),
        )
    assert exc_info.value.code == "annotation_thread_cursor_invalid"
    assert "invalid or expired" in exc_info.value.message

    with pytest.raises(AppError) as actor_exc:
        handler.list_annotation_threads(
            capabilities,
            _context(actor_id=8),
            request.model_copy(update={"cursor": first.next_cursor}),
        )
    assert actor_exc.value.code == "annotation_thread_cursor_invalid"


def test_legal_max_annotation_page_stays_inside_real_call_tool_result_budget() -> None:
    document_id = uuid4()
    hostile_text = ('\x00\\"中🙂' * 30_000)[:100_000]
    summaries = [
        project_annotation_summary(
            _summary(
                document_id=document_id,
                quote_text=hostile_text,
                display_name=hostile_text,
            )
        )
        for _ in range(ANNOTATION_SUMMARY_MAX_PAGE_ITEMS)
    ]
    capabilities = MagicMock()
    capabilities.research_items.list_annotation_thread_summaries_page.return_value = (
        AnnotationThreadSummaryPage(
            items=summaries,
            next_keyset=_keyset(summaries[-1].id, summaries[-1].created_at),
        )
    )

    outcome = _handler().list_annotation_threads(
        capabilities,
        _context(),
        ListAnnotationThreadsInput(document_id=document_id, limit=100),
    )
    page = ThreadListOutput.model_validate(outcome.payload)
    serialized = serialize_tool_success(outcome)

    assert (
        ListAnnotationThreadsInput.model_json_schema()["properties"]["limit"]["maximum"]
        == 100
    )
    assert len(page.items) == ANNOTATION_SUMMARY_MAX_PAGE_ITEMS
    assert (
        capabilities.research_items.list_annotation_thread_summaries_page.call_args.kwargs[
            "limit"
        ]
        == ANNOTATION_SUMMARY_MAX_PAGE_ITEMS
    )
    assert all(item.comments == [] for item in page.items)
    assert all(
        len(json.dumps(item.quote_text, ensure_ascii=False).encode("utf-8"))
        <= ANNOTATION_SUMMARY_QUOTE_JSON_BYTES
        for item in page.items
    )
    assert all(
        isinstance(item.position, PdfTextPosition) and len(item.position.rects) == 1
        for item in page.items
    )
    assert serialized.call_tool_result_utf8_bytes < DEFAULT_TOOL_OUTPUT_BYTES
