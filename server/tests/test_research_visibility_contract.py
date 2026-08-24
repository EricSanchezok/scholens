"""Contracts for audience-scoped Research items and annotation threads."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import pytest
from app.bootstrap.adapters.project_presenters import _project_counts
from app.bootstrap.adapters.research_items import SqlAlchemyResearchItemGateway
from app.bootstrap.adapters.research_access import (
    research_item_policy,
    research_item_visible_to,
)
from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.database.models import (
    AnnotationColor,
    AnnotationComment,
    AnnotationThread,
    AuthUser,
    CitationOutput,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    ResearchAudienceType,
    RoleType,
)
from app.main import app
from app.modules.research.application.contracts import (
    AnnotationThreadMode,
    AnnotationThreadStatus,
    CitationSnapshot,
    CreateAnnotationThreadRequest,
    ProjectResearchAudience,
    UpdateAnnotationThreadRequest,
)
from app.modules.research.application.positions import (
    ParsedTextPosition,
    PdfTextPageSegment,
    PdfTextPosition,
)
from app.shared.domain import AppError
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def _item(
    *,
    creator_id: int = 2,
    audience_type: ResearchAudienceType = ResearchAudienceType.PROJECT,
) -> ResearchItem:
    return ResearchItem(
        id=uuid.uuid4(),
        kind=ResearchItemKind.CITATION.value,
        created_by_id=creator_id,
        audience_type=audience_type.value,
        audience_project_id=(
            uuid.uuid4() if audience_type is ResearchAudienceType.PROJECT else None
        ),
        audience_document_id=(
            uuid.uuid4() if audience_type is ResearchAudienceType.DOCUMENT else None
        ),
    )


def test_research_items_use_explicit_audience_and_target_contract() -> None:
    assert {
        "kind",
        "created_by_id",
        "audience_type",
        "audience_document_id",
        "audience_project_id",
        "target_document_id",
        "source_response_id",
    }.issubset(ResearchItem.__table__.c.keys())
    for removed in ("scope_type", "document_id", "project_id", "is_shared"):
        assert removed not in ResearchItem.__table__.c
    assert AnnotationThread.__table__.c.research_item_id.primary_key
    assert ResearchAudioOverview.__table__.c.research_item_id.primary_key
    assert ResearchDataTable.__table__.c.research_item_id.primary_key
    assert "parent_comment_id" not in AnnotationComment.__table__.c
    assert "color" not in AnnotationComment.__table__.c


def test_project_audience_members_can_view_but_only_creator_can_manage() -> None:
    db = MagicMock(spec=Session)
    item = _item(creator_id=2)

    def project_access(*_args: object, user_id: int, **_kwargs: object) -> object:
        return SimpleNamespace(can_edit_project=user_id == 1)

    with patch(
        "app.bootstrap.adapters.research_access.get_project_access",
        side_effect=project_access,
    ):
        creator = research_item_policy.evaluate(db, item=item, user_id=2)
        collaborator = research_item_policy.evaluate(db, item=item, user_id=3)
        owner = research_item_policy.evaluate(db, item=item, user_id=1)

    assert creator.can_view and creator.can_manage and creator.can_resolve
    assert collaborator.can_view and not collaborator.can_manage
    assert owner.can_view and not owner.can_manage and owner.can_resolve


def test_project_member_loses_thread_access_immediately_after_leaving() -> None:
    db = MagicMock(spec=Session)
    item = _item(creator_id=2)
    with patch(
        "app.bootstrap.adapters.research_access.get_project_access",
        return_value=None,
    ):
        access = research_item_policy.evaluate(db, item=item, user_id=2)
    assert not access.can_view
    assert not access.has_audience_access


def test_research_item_visibility_sql_has_no_shared_bypass() -> None:
    statement = str(
        research_item_visible_to(7).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "research_items.created_by_id = 7" in statement
    assert "library_papers.user_id = 7" in statement
    assert "project_collaborators.user_id = 7" in statement
    assert "is_shared" not in statement


def test_comment_capabilities_become_read_only_when_audience_access_is_lost() -> None:
    now = datetime.now(timezone.utc)
    comment = AnnotationComment(
        id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        created_by_id=2,
        content="Observation",
        role="user",
        created_at=now,
        updated_at=now,
    )
    response = research_repository.serialize_comment(
        comment,
        user_id=2,
        has_audience_access=False,
    )
    assert response.can_edit is False
    assert response.can_delete is False


def test_thread_creation_atomically_attaches_initial_flat_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    document = SimpleNamespace(id=uuid.uuid4(), raw_content="Evidence")
    db.scalar.return_value = document
    monkeypatch.setattr(
        "app.bootstrap.adapters.research_repository.require_document_access",
        lambda *_args, **_kwargs: SimpleNamespace(document=document),
    )
    item = research_repository.create_annotation_thread(
        db,
        document_id=uuid.uuid4(),
        user_id=2,
        create=AnnotationThreadCreate(
            quote_text="Evidence",
            position=ParsedTextPosition(start_offset=0, end_offset=8),
            color="yellow",
            audience_type=ResearchAudienceType.PERSONAL,
            audience_project_id=None,
            content_role=RoleType.USER,
            initial_comment="This matters.",
        ),
        refresh_result=False,
    )
    assert item.annotation_thread is not None
    assert [comment.content for comment in item.annotation_thread.comments] == [
        "This matters."
    ]
    source_lock = db.scalar.call_args_list[0].args[0]
    source_lock_sql = str(source_lock.compile(dialect=postgresql.dialect()))
    assert "documents.id" in source_lock_sql
    assert "FOR UPDATE" in source_lock_sql
    assert source_lock.get_execution_options()["populate_existing"] is True


def test_parsed_text_annotation_requires_canonical_content() -> None:
    access = SimpleNamespace(document=SimpleNamespace(raw_content=None))
    create = AnnotationThreadCreate(
        quote_text="Evidence",
        position=ParsedTextPosition(start_offset=0, end_offset=8),
        color="yellow",
        audience_type=ResearchAudienceType.PERSONAL,
        audience_project_id=None,
        content_role=RoleType.USER,
        initial_comment=None,
    )

    with pytest.raises(AppError) as exc_info:
        research_repository._validate_quote_position(access.document, create)

    assert exc_info.value.code == "annotation_content_unavailable"


@pytest.mark.parametrize(
    ("audience_type", "comment_count", "expected_mode"),
    [
        (ResearchAudienceType.PERSONAL, 0, AnnotationThreadMode.HIGHLIGHT),
        (ResearchAudienceType.PROJECT, 0, AnnotationThreadMode.HIGHLIGHT),
        (ResearchAudienceType.PERSONAL, 1, AnnotationThreadMode.NOTE),
        (ResearchAudienceType.PROJECT, 2, AnnotationThreadMode.DISCUSSION),
    ],
)
def test_annotation_summary_derives_mode_and_activity(
    monkeypatch: pytest.MonkeyPatch,
    audience_type: ResearchAudienceType,
    comment_count: int,
    expected_mode: AnnotationThreadMode,
) -> None:
    now = datetime.now(timezone.utc)
    item = _item(creator_id=2, audience_type=audience_type)
    item.kind = ResearchItemKind.ANNOTATION_THREAD.value
    item.target_document_id = uuid.uuid4()
    item.created_at = now
    item.updated_at = now
    item.annotation_thread = AnnotationThread(
        quote_text="Evidence",
        color="yellow",
        role="user",
        status="open",
    )
    item.annotation_thread.comments = [
        AnnotationComment(
            id=uuid.uuid4(),
            thread_id=item.id,
            content=f"Comment {index + 1}",
            role="user",
            created_by_id=2,
            created_at=now,
            updated_at=now,
        )
        for index in range(comment_count)
    ]
    monkeypatch.setattr(
        research_item_policy,
        "require_visible",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_audience_access=True,
            can_manage=True,
            can_resolve=audience_type is ResearchAudienceType.PROJECT,
        ),
    )

    summary = research_repository.serialize_annotation_summary(
        MagicMock(spec=Session),
        item=item,
        user_id=2,
        comment_count=comment_count,
        last_activity_at=now,
        has_foreign_replies=False,
    )

    assert summary.mode is expected_mode
    assert summary.comment_count == comment_count
    assert summary.last_activity_at == now
    assert summary.capabilities.resolve is (
        expected_mode is AnnotationThreadMode.DISCUSSION
    )
    assert summary.capabilities.delete is True
    assert [comment.content for comment in summary.comments] == [
        f"Comment {index + 1}" for index in range(comment_count)
    ]


def test_annotation_list_orders_by_document_position_not_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    db.execute.return_value.unique.return_value = []
    monkeypatch.setattr(
        "app.bootstrap.adapters.research_repository.require_document_access",
        lambda *_args, **_kwargs: object(),
    )
    research_repository.list_annotation_summaries(
        db,
        document_id=uuid.uuid4(),
        user_id=2,
        project_id=None,
        audience=None,
        mode=None,
        status=AnnotationThreadStatus.OPEN,
    )
    statement = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))

    assert "annotation_threads.page_number ASC NULLS LAST" in statement
    assert "CAST" in statement
    assert "annotation_threads.position" in statement
    assert "annotation_threads.start_offset ASC NULLS LAST" in statement
    assert "last_activity_at DESC" not in statement


def test_thread_with_other_authors_cannot_be_hard_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item(creator_id=2, audience_type=ResearchAudienceType.PERSONAL)
    item.kind = ResearchItemKind.ANNOTATION_THREAD.value
    db = MagicMock(spec=Session)
    db.scalar.return_value = 3
    monkeypatch.setattr(
        research_repository,
        "require_creator_owned",
        lambda *_args, **_kwargs: item,
    )
    with pytest.raises(AppError) as exc_info:
        operation_id = uuid.uuid4()
        research_repository.delete_item(
            db,
            item_id=item.id,
            user_id=2,
            origin_operation_id=operation_id,
            correlation_id=operation_id,
        )
    assert exc_info.value.code == "annotation_thread_has_other_replies"
    assert exc_info.value.details == {"affected_reply_count": 3}
    db.delete.assert_not_called()


def test_resolved_thread_blocks_replies_and_reopen_clears_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item(creator_id=2)
    item.kind = ResearchItemKind.ANNOTATION_THREAD.value
    item.annotation_thread = AnnotationThread(
        quote_text="Evidence",
        color="yellow",
        role="user",
        status="resolved",
        resolved_by_id=2,
        resolved_at=datetime.now(timezone.utc),
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = item.annotation_thread
    monkeypatch.setattr(
        research_repository,
        "require_visible",
        lambda *_args, **_kwargs: item,
    )
    monkeypatch.setattr(
        research_item_policy,
        "evaluate",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_audience_access=True,
            can_manage=True,
            can_resolve=True,
        ),
    )

    with pytest.raises(AppError) as exc_info:
        research_repository.add_comment(
            db,
            thread_id=item.id,
            user_id=2,
            content="Late reply",
            content_role=RoleType.USER,
        )
    assert exc_info.value.code == "annotation_thread_resolved"

    result = research_repository.update_annotation_thread(
        db,
        thread_id=item.id,
        user_id=2,
        values={"status": AnnotationThreadStatus.OPEN},
    )
    assert result.changed
    assert item.annotation_thread.status == "open"
    assert item.annotation_thread.resolved_by_id is None
    assert item.annotation_thread.resolved_at is None


def test_resolving_historical_thread_checks_comment_existence_without_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HistoricalThread:
        color = "yellow"
        status = "open"
        resolved_by_id = None
        resolved_at = None

        @property
        def comments(self) -> object:  # pragma: no cover - access is the regression
            raise AssertionError("historical comment bodies must not be hydrated")

    item = SimpleNamespace(
        id=uuid.uuid4(),
        kind=ResearchItemKind.ANNOTATION_THREAD.value,
        audience_type=ResearchAudienceType.PROJECT.value,
        annotation_thread=HistoricalThread(),
        updated_at=datetime.now(timezone.utc),
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = uuid.uuid4()
    monkeypatch.setattr(
        research_repository,
        "require_visible",
        lambda *_args, **_kwargs: item,
    )
    monkeypatch.setattr(
        research_item_policy,
        "evaluate",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_audience_access=True,
            can_manage=True,
            can_resolve=True,
        ),
    )

    result = research_repository.update_annotation_thread(
        db,
        thread_id=item.id,
        user_id=2,
        values={"status": AnnotationThreadStatus.RESOLVED},
    )

    assert result.changed is True
    assert item.annotation_thread.status == "resolved"
    statement = db.scalar.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == ("id",)
    assert "content" not in str(statement)


def test_bounded_annotation_update_gateway_never_calls_full_serializer() -> None:
    db = MagicMock(spec=Session)
    item = _item(creator_id=2)
    bounded_response = MagicMock()
    gateway = SqlAlchemyResearchItemGateway(db)

    with (
        patch.object(
            research_repository,
            "update_annotation_thread",
            return_value=SimpleNamespace(value=item, changed=True),
        ),
        patch.object(
            research_repository,
            "serialize_annotation_mutation_response",
            return_value=bounded_response,
        ) as bounded_serializer,
        patch.object(gateway, "_serialize") as full_serializer,
    ):
        result = gateway.update_annotation_thread_bounded(
            user_id=2,
            thread_id=item.id,
            request=UpdateAnnotationThreadRequest(color=AnnotationColor.YELLOW),
        )

    assert result.value is bounded_response
    assert result.changed is True
    bounded_serializer.assert_called_once_with(db, item=item, user_id=2)
    full_serializer.assert_not_called()


def test_annotation_request_uses_immutable_discriminated_audience() -> None:
    project_id = uuid.uuid4()
    request = CreateAnnotationThreadRequest.model_validate(
        {
            "quote_text": "Evidence",
            "position": {
                "kind": "pdf_text",
                "page_number": 1,
                "rects": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}],
            },
            "audience": {"kind": "project", "project_id": str(project_id)},
            "initial_comment": "Discuss this.",
        }
    )
    assert request.audience == ProjectResearchAudience(project_id=project_id)
    assert request.color.value == "yellow"

    with pytest.raises(ValidationError):
        CreateAnnotationThreadRequest.model_validate(
            {
                "quote_text": "Evidence",
                "position": {
                    "kind": "parsed_text",
                    "start_offset": 0,
                    "end_offset": 8,
                },
                "audience": {"kind": "document", "document_id": str(uuid.uuid4())},
            }
        )
    with pytest.raises(ValidationError):
        CreateAnnotationThreadRequest.model_validate(
            {"quote_text": "Evidence", "shared": True}
        )


def test_pdf_text_position_accepts_legacy_and_ordered_page_segments() -> None:
    rect = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}
    legacy = CreateAnnotationThreadRequest.model_validate(
        {
            "quote_text": "Legacy",
            "position": {"kind": "pdf_text", "page_number": 2, "rects": [rect]},
        }
    ).position
    assert isinstance(legacy, PdfTextPosition)
    assert legacy.segments is None

    cross_page = CreateAnnotationThreadRequest.model_validate(
        {
            "quote_text": "Across pages",
            "position": {
                "kind": "pdf_text",
                "page_number": 2,
                "rects": [rect],
                "segments": [
                    {"page_number": 2, "rects": [rect]},
                    {
                        "page_number": 3,
                        "rects": [{"x": 0.2, "y": 0.1, "width": 0.4, "height": 0.04}],
                    },
                ],
            },
        }
    ).position
    assert isinstance(cross_page, PdfTextPosition)
    assert cross_page.segments is not None
    assert [segment.page_number for segment in cross_page.segments] == [2, 3]

    with pytest.raises(ValidationError):
        CreateAnnotationThreadRequest.model_validate(
            {
                "quote_text": "Invalid",
                "position": {
                    "kind": "pdf_text",
                    "page_number": 2,
                    "rects": [rect],
                    "segments": [
                        {"page_number": 3, "rects": [rect]},
                        {"page_number": 2, "rects": [rect]},
                    ],
                },
            }
        )

    for invalid_segments in (
        [
            {"page_number": 2, "rects": [rect]},
            {"page_number": 2, "rects": [rect]},
        ],
        [{"page_number": 3, "rects": [rect]}],
    ):
        with pytest.raises(ValidationError):
            CreateAnnotationThreadRequest.model_validate(
                {
                    "quote_text": "Invalid projection",
                    "position": {
                        "kind": "pdf_text",
                        "page_number": 2,
                        "rects": [rect],
                        "segments": invalid_segments,
                    },
                }
            )


def test_annotation_positions_match_the_persisted_integer_range() -> None:
    maximum = (1 << 31) - 1
    rect = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}

    assert (
        ParsedTextPosition(
            start_offset=maximum - 1,
            end_offset=maximum,
            page_number=maximum,
        ).end_offset
        == maximum
    )
    assert (
        PdfTextPosition(
            page_number=maximum,
            rects=[rect],
        ).page_number
        == maximum
    )
    assert (
        PdfTextPageSegment(
            page_number=maximum,
            rects=[rect],
        ).page_number
        == maximum
    )
    with pytest.raises(ValidationError):
        ParsedTextPosition(start_offset=0, end_offset=maximum + 1)
    with pytest.raises(ValidationError):
        ParsedTextPosition(start_offset=maximum + 1, end_offset=maximum + 2)
    with pytest.raises(ValidationError):
        ParsedTextPosition(
            start_offset=0,
            end_offset=1,
            page_number=maximum + 1,
        )
    with pytest.raises(ValidationError):
        PdfTextPosition(page_number=maximum + 1, rects=[rect])
    with pytest.raises(ValidationError):
        PdfTextPageSegment(page_number=maximum + 1, rects=[rect])

    parsed_schema = ParsedTextPosition.model_json_schema()["properties"]
    pdf_schema = PdfTextPosition.model_json_schema()["properties"]
    segment_schema = PdfTextPageSegment.model_json_schema()["properties"]
    assert parsed_schema["start_offset"]["maximum"] == maximum
    assert parsed_schema["end_offset"]["maximum"] == maximum
    assert parsed_schema["page_number"]["anyOf"][0]["maximum"] == maximum
    assert pdf_schema["page_number"]["maximum"] == maximum
    assert segment_schema["page_number"]["maximum"] == maximum


def test_pdf_text_position_caps_total_segment_rectangles() -> None:
    rect = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}
    first_page_rects = [rect] * 100

    accepted = CreateAnnotationThreadRequest.model_validate(
        {
            "quote_text": "Bounded geometry",
            "position": {
                "kind": "pdf_text",
                "page_number": 2,
                "rects": first_page_rects,
                "segments": [
                    {"page_number": 2, "rects": first_page_rects},
                    {"page_number": 3, "rects": [rect] * 100},
                ],
            },
        }
    ).position
    assert isinstance(accepted, PdfTextPosition)
    assert accepted.segments is not None
    assert sum(len(segment.rects) for segment in accepted.segments) == 200

    with pytest.raises(ValidationError, match="at most 200 rectangles"):
        CreateAnnotationThreadRequest.model_validate(
            {
                "quote_text": "Oversized geometry",
                "position": {
                    "kind": "pdf_text",
                    "page_number": 2,
                    "rects": first_page_rects,
                    "segments": [
                        {"page_number": 2, "rects": first_page_rects},
                        {"page_number": 3, "rects": [rect] * 101},
                    ],
                },
            }
        )


def test_citation_snapshot_is_strictly_validated_before_persistence() -> None:
    snapshot = CitationSnapshot.model_validate(
        {
            "kind": "citation",
            "document_id": str(uuid.uuid4()),
            "preferred_style": "APA",
            "style_display": "APA 7th Edition",
            "data": {
                "document_id": str(uuid.uuid4()),
                "title": "Typed citation",
                "authors": ["Researcher"],
            },
            "method": "deterministic",
            "missing_fields": [],
            "confidence": 0.95,
        }
    )
    with pytest.raises(ValidationError):
        CitationSnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "private_trace": {"query": "must not persist"},
            }
        )


def test_research_api_exposes_annotation_thread_routes_only() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/papers/{document_id}/research-items",
        "/api/v1/papers/{document_id}/annotation-threads",
        "/api/v1/annotation-threads/{thread_id}",
        "/api/v1/annotation-threads/{thread_id}/comments",
        "/api/v1/annotation-comments/{comment_id}",
        "/api/v1/projects/{project_id}/research-items",
        "/api/v1/research-items/{item_id}",
    }
    assert expected.issubset(paths)
    assert not any("highlight-thread" in path for path in paths)
    assert not any("/visibility" in path for path in paths)


def test_project_summary_counts_project_audience_outputs() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0

    _project_counts(db, project_id=uuid.uuid4(), current_user_id=73)
    output_statement = str(db.scalar.call_args_list[2].args[0])
    assert "research_items.audience_type" in output_statement
    assert "research_items.audience_project_id" in output_statement
    assert "is_shared" not in output_statement


def test_clean_baseline_contains_annotation_audience_constraints() -> None:
    baseline = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))[0]
    source = baseline.read_text(encoding="utf-8")
    for table_or_constraint in (
        "research_items",
        "annotation_threads",
        "annotation_comments",
        "ck_research_items_audience_consistency",
        "ck_research_items_annotation_audience",
        "ck_annotation_threads_resolution",
    ):
        assert table_or_constraint in source
    for legacy in (
        "highlight_threads",
        "is_shared",
        "ck_research_items_scope_consistency",
    ):
        assert legacy not in source


def _creator_user(
    *,
    display_name: str | None = None,
    email: str = "teammate@example.com",
) -> AuthUser:
    return AuthUser(
        id=7,
        email=email,
        password_hash="not-used-in-tests",
        display_name=display_name,
        status="active",
    )


def test_creator_response_prefers_display_name() -> None:
    response = research_repository._creator_response(
        7,
        _creator_user(display_name="Ada Researcher"),
    )
    assert response.id == 7
    assert response.display_name == "Ada Researcher"


@pytest.mark.parametrize("display_name", [None, "", "   "])
def test_creator_response_falls_back_to_email_when_display_name_is_blank(
    display_name: str | None,
) -> None:
    response = research_repository._creator_response(
        7,
        _creator_user(display_name=display_name),
    )
    assert response.display_name == "teammate@example.com"


def test_creator_response_keeps_unknown_author_when_user_is_gone() -> None:
    response = research_repository._creator_response(None, None)
    assert response.id is None
    assert response.display_name is None


def test_comment_serialization_exposes_creator_email_fallback() -> None:
    now = datetime.now(timezone.utc)
    comment = AnnotationComment(
        id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        created_by_id=7,
        content="Observation",
        role="user",
        created_at=now,
        updated_at=now,
    )
    comment.created_by = _creator_user(display_name=None)

    response = research_repository.serialize_comment(
        comment,
        user_id=7,
        has_audience_access=True,
    )
    assert response.created_by.id == 7
    assert response.created_by.display_name == "teammate@example.com"


def test_item_serialization_exposes_creator_email_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    now = datetime.now(timezone.utc)
    item = _item(creator_id=7)
    item.created_at = now
    item.updated_at = now
    item.created_by = _creator_user(display_name="   ")
    item.citation = CitationOutput(
        snapshot={
            "kind": "citation",
            "document_id": str(uuid.uuid4()),
            "preferred_style": "APA",
            "style_display": "APA 7th Edition",
            "data": {
                "document_id": str(uuid.uuid4()),
                "title": "Typed citation",
                "authors": ["Researcher"],
            },
            "method": "deterministic",
            "missing_fields": [],
            "confidence": 0.95,
        }
    )
    monkeypatch.setattr(
        research_item_policy,
        "require_visible",
        lambda *_args, **_kwargs: SimpleNamespace(
            has_audience_access=True,
            can_manage=True,
            can_resolve=True,
        ),
    )

    response = research_repository.serialize(db, item=item, user_id=7)
    assert response.created_by.id == 7
    assert response.created_by.display_name == "teammate@example.com"
