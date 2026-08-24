"""Regression coverage for bounded, live-state deletion confirmation plans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.bootstrap.adapters.project_gateway import SqlAlchemyProjectGateway
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import AnnotationComment
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind

NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


def _streaming_rows(rows: list[tuple[object, ...]]) -> MagicMock:
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    result.all.side_effect = AssertionError("digest scan must not materialize all rows")
    return result


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email=f"researcher-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _project_gateway(db: Session) -> SqlAlchemyProjectGateway:
    return SqlAlchemyProjectGateway(
        db,
        invitation_tokens=ProjectInvitationTokenCodec(
            "deletion-plan-test-secret-at-least-32-bytes"
        ),
    )


def _project(*, project_id: object, title: str = "Evidence review") -> object:
    return SimpleNamespace(
        id=project_id,
        owner_id=7,
        title=title,
        updated_at=NOW,
    )


def _annotation_item(*, thread_id: object, creator_id: int = 7) -> object:
    return SimpleNamespace(
        id=thread_id,
        kind=ResearchItemKind.ANNOTATION_THREAD.value,
        created_by_id=creator_id,
        updated_at=NOW,
    )


def test_project_paper_removal_plan_requires_manage_permission_before_reads() -> None:
    db = MagicMock(spec=Session)
    project_id = uuid4()
    document_id = uuid4()
    denied = AppError(
        code="project_permission_denied",
        message="Project permission denied",
        kind=FailureKind.PERMISSION_DENIED,
    )

    with (
        patch(
            "app.bootstrap.adapters.project_gateway.require_project_permission_for_update",
            side_effect=denied,
        ) as require_permission,
        pytest.raises(AppError) as exc_info,
    ):
        _project_gateway(db).plan_remove_document(
            actor=_actor(),
            project_id=project_id,
            document_id=document_id,
        )

    assert exc_info.value.code == "project_permission_denied"
    require_permission.assert_called_once_with(
        db,
        project_id=project_id,
        user_id=7,
        permission="manage_papers",
    )
    db.scalar.assert_not_called()
    db.execute.assert_not_called()


def test_project_paper_removal_plan_rejects_missing_association_before_impact() -> None:
    db = MagicMock(spec=Session)
    project_id = uuid4()
    document_id = uuid4()
    db.scalar.side_effect = [document_id, None]

    with (
        patch(
            "app.bootstrap.adapters.project_gateway.require_project_permission_for_update",
            return_value=SimpleNamespace(project=_project(project_id=project_id)),
        ),
        pytest.raises(AppError) as exc_info,
    ):
        _project_gateway(db).plan_remove_document(
            actor=_actor(),
            project_id=project_id,
            document_id=document_id,
        )

    assert exc_info.value.code == "project_document_not_found"
    db.execute.assert_not_called()


def test_project_paper_removal_plan_counts_threads_and_binds_comment_revision() -> None:
    db = MagicMock(spec=Session)
    project_id = uuid4()
    document_id = uuid4()
    association_id = uuid4()
    first_thread_id = uuid4()
    second_thread_id = uuid4()
    first_comment_id = uuid4()
    second_comment_id = uuid4()
    db.scalar.side_effect = [
        document_id,
        association_id,
        document_id,
        association_id,
    ]
    thread_rows = [
        (first_thread_id, NOW, NOW),
        (second_thread_id, NOW, NOW),
    ]
    initial_comment_rows = [
        (first_comment_id, 7, NOW),
        (second_comment_id, 7, NOW),
    ]
    revised_comment_rows = [
        initial_comment_rows[0],
        (second_comment_id, 7, NOW + timedelta(seconds=1)),
    ]
    db.execute.side_effect = [
        thread_rows,
        initial_comment_rows,
        thread_rows,
        revised_comment_rows,
    ]
    access = SimpleNamespace(project=_project(project_id=project_id))

    with patch(
        "app.bootstrap.adapters.project_gateway.require_project_permission_for_update",
        return_value=access,
    ):
        first = _project_gateway(db).plan_remove_document(
            actor=_actor(),
            project_id=project_id,
            document_id=document_id,
        )
        revised = _project_gateway(db).plan_remove_document(
            actor=_actor(),
            project_id=project_id,
            document_id=document_id,
        )

    assert first.state.annotation_thread_count == 2
    assert first.state.annotation_comment_count == 2
    assert revised.state.annotation_thread_count == 2
    assert revised.state.annotation_comment_count == 2
    assert (
        first.state.annotation_revision_digest
        != revised.state.annotation_revision_digest
    )


def test_project_paper_removal_plan_never_loads_hostile_comment_content() -> None:
    db = MagicMock(spec=Session)
    project_id = uuid4()
    document_id = uuid4()
    thread_id = uuid4()
    hostile_comment = AnnotationComment(
        id=uuid4(),
        thread_id=thread_id,
        created_by_id=7,
        content="秘密" * 100_000,
        role="user",
        created_at=NOW,
        updated_at=NOW,
    )
    db.scalar.side_effect = [document_id, uuid4()]
    db.execute.side_effect = [
        _streaming_rows([(thread_id, NOW, NOW)]),
        _streaming_rows(
            [
                (
                    hostile_comment.id,
                    hostile_comment.created_by_id,
                    hostile_comment.updated_at,
                )
            ]
        ),
    ]

    with patch(
        "app.bootstrap.adapters.project_gateway.require_project_permission_for_update",
        return_value=SimpleNamespace(project=_project(project_id=project_id)),
    ):
        plan = _project_gateway(db).plan_remove_document(
            actor=_actor(),
            project_id=project_id,
            document_id=document_id,
        )

    statement = str(db.execute.call_args.args[0])
    state_json = plan.state.model_dump_json()
    assert "annotation_comments.content" not in statement
    assert all(
        call.args[0].get_execution_options().get("yield_per") == 100
        for call in db.execute.call_args_list
    )
    assert hostile_comment.content[:100] not in state_json
    assert len(state_json.encode("utf-8")) < 1_000


def test_annotation_deletion_plan_requires_creator_before_revision_reads() -> None:
    db = MagicMock(spec=Session)
    thread_id = uuid4()
    denied = AppError(
        code="research_item_permission_denied",
        message="Only the creator can delete this annotation thread",
        kind=FailureKind.PERMISSION_DENIED,
    )

    with (
        patch.object(
            research_repository,
            "require_creator_owned",
            side_effect=denied,
        ) as require_creator,
        pytest.raises(AppError) as exc_info,
    ):
        research_repository.plan_annotation_thread_delete(
            db,
            thread_id=thread_id,
            user_id=7,
        )

    assert exc_info.value.code == "research_item_permission_denied"
    require_creator.assert_called_once_with(
        db,
        item_id=thread_id,
        user_id=7,
        for_update=True,
    )
    db.scalar.assert_not_called()
    db.execute.assert_not_called()


def test_annotation_deletion_plan_rejects_foreign_replies_before_digest_scan() -> None:
    db = MagicMock(spec=Session)
    thread_id = uuid4()
    db.scalar.return_value = NOW
    db.execute.return_value = [(uuid4(), 9, NOW) for _index in range(3)]

    with (
        patch.object(
            research_repository,
            "require_creator_owned",
            return_value=_annotation_item(thread_id=thread_id),
        ),
        pytest.raises(AppError) as exc_info,
    ):
        research_repository.plan_annotation_thread_delete(
            db,
            thread_id=thread_id,
            user_id=7,
        )

    assert exc_info.value.code == "annotation_thread_has_other_replies"
    assert exc_info.value.details == {"affected_reply_count": 3}


def test_annotation_deletion_plan_digest_changes_with_comment_revision() -> None:
    db = MagicMock(spec=Session)
    thread_id = uuid4()
    comment_id = uuid4()
    db.scalar.side_effect = [NOW, NOW]
    db.execute.side_effect = [
        [(comment_id, 7, NOW)],
        [(comment_id, 7, NOW + timedelta(seconds=1))],
    ]

    with patch.object(
        research_repository,
        "require_creator_owned",
        return_value=_annotation_item(thread_id=thread_id),
    ):
        first = research_repository.plan_annotation_thread_delete(
            db,
            thread_id=thread_id,
            user_id=7,
        )
        revised = research_repository.plan_annotation_thread_delete(
            db,
            thread_id=thread_id,
            user_id=7,
        )

    assert first.state.comment_count == revised.state.comment_count == 1
    assert first.state.comment_revision_digest != revised.state.comment_revision_digest


def test_annotation_deletion_plan_never_loads_hostile_comment_content() -> None:
    db = MagicMock(spec=Session)
    thread_id = uuid4()
    hostile_comment = AnnotationComment(
        id=uuid4(),
        thread_id=thread_id,
        created_by_id=7,
        content="秘密" * 100_000,
        role="user",
        created_at=NOW,
        updated_at=NOW,
    )
    db.scalar.return_value = NOW
    db.execute.return_value = _streaming_rows(
        [
            (
                hostile_comment.id,
                hostile_comment.created_by_id,
                hostile_comment.updated_at,
            )
        ]
    )

    with patch.object(
        research_repository,
        "require_creator_owned",
        return_value=_annotation_item(thread_id=thread_id),
    ):
        plan = research_repository.plan_annotation_thread_delete(
            db,
            thread_id=thread_id,
            user_id=7,
        )

    statement = str(db.execute.call_args.args[0])
    state_json = plan.state.model_dump_json()
    assert "annotation_comments.content" not in statement
    assert statement != ""
    assert db.execute.call_args.args[0].get_execution_options().get("yield_per") == 100
    assert hostile_comment.content[:100] not in state_json
    assert len(state_json.encode("utf-8")) < 700
