"""Contracts for audience-scoped Research items and annotation threads."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import pytest
from app.bootstrap.adapters.project_presenters import _project_counts
from app.bootstrap.adapters.research_access import (
    research_item_policy,
    research_item_visible_to,
)
from app.bootstrap.adapters.research_repository import (
    AnnotationThreadCreate,
    research_repository,
)
from app.database.models import (
    AnnotationComment,
    AnnotationThread,
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
)
from app.modules.research.application.positions import ParsedTextPosition
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
    monkeypatch.setattr(
        "app.bootstrap.adapters.research_repository.require_document_access",
        lambda *_args, **_kwargs: object(),
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
