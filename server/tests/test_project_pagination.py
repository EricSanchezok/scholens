from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.bootstrap.adapters.project_gateway import SqlAlchemyProjectGateway
from app.modules.papers.application.contracts.documents import (
    LibraryOutputResponse,
    LibraryOutputSort,
    PaperStatus,
)
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.modules.projects.application.contracts import (
    ProjectPaperSort,
    ProjectPaperSummaryResponse,
    ProjectResponse,
    ProjectSort,
)
from app.modules.projects.application.projects import (
    ProjectOutputPage,
    ProjectPage,
    ProjectPageDirection,
    ProjectPagePosition,
    ProjectPaperPage,
    Projects,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _projects(*, gateway: MagicMock) -> Projects:
    return Projects(
        gateway=gateway,
        capacity=MagicMock(),
        signer=MagicMock(),
        cursors=SignedCursorCodec(
            "projects-test-secret",
            revision="projects-v1",
            error_code="project_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=MagicMock(),
    )


def _page(*, item_id: UUID, has_more: bool) -> ProjectPage:
    return ProjectPage(
        items=[ProjectResponse.model_construct(id=item_id)],
        positions=[ProjectPagePosition(key="2026-08-13T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def test_project_cursor_is_query_bound_and_supports_previous_navigation() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_projects.side_effect = [
        _page(item_id=first_id, has_more=True),
        _page(item_id=second_id, has_more=False),
        _page(item_id=first_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)

    first = projects.list(actor=_actor(), query="retrieval", limit=1)
    assert first.next_cursor is not None
    assert first.previous_cursor is None
    assert first.total_count == 2

    second = projects.list(
        actor=_actor(), query="retrieval", limit=1, cursor=first.next_cursor
    )
    assert second.previous_cursor is not None
    assert second.next_cursor is None
    assert gateway.list_projects.call_args_list[1].kwargs["direction"] is (
        ProjectPageDirection.FORWARD
    )
    assert gateway.list_projects.call_args_list[1].kwargs["position"].id == first_id

    previous = projects.list(
        actor=_actor(), query="retrieval", limit=1, cursor=second.previous_cursor
    )
    assert previous.next_cursor is not None
    assert gateway.list_projects.call_args_list[2].kwargs["direction"] is (
        ProjectPageDirection.BACKWARD
    )


@pytest.mark.parametrize(
    ("changed_argument", "value"),
    [
        ("query", "different"),
        ("sort", ProjectSort.TITLE_ASC),
        ("actor", _actor(8)),
    ],
)
def test_project_cursor_rejects_cross_query_reuse(
    changed_argument: str,
    value: object,
) -> None:
    gateway = MagicMock()
    gateway.list_projects.return_value = _page(item_id=uuid4(), has_more=True)
    projects = _projects(gateway=gateway)
    first = projects.list(actor=_actor(), query="retrieval", limit=1)
    arguments: dict[str, object] = {
        "actor": _actor(),
        "query": "retrieval",
        "sort": ProjectSort.ACTIVITY_DESC,
        "limit": 1,
        "cursor": first.next_cursor,
    }
    arguments[changed_argument] = value

    with pytest.raises(AppError, match="cursor") as raised:
        projects.list(**arguments)  # type: ignore[arg-type]

    assert raised.value.code == "project_cursor_invalid"


def test_project_cursor_survives_page_size_changes() -> None:
    """Page size is a preference, not a filter: the same keyset cursor must
    remain valid when the caller changes limit between pages."""
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_projects.side_effect = [
        _page(item_id=first_id, has_more=True),
        _page(item_id=second_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)

    first = projects.list(actor=_actor(), query="retrieval", limit=1)
    resized = projects.list(
        actor=_actor(),
        query="retrieval",
        limit=50,
        cursor=first.next_cursor,
    )

    assert resized.total_count == 2
    assert gateway.list_projects.call_args_list[1].kwargs["position"].id == first_id
    assert gateway.list_projects.call_args_list[1].kwargs["limit"] == 50


def _paper_page(*, item_id: UUID, has_more: bool) -> ProjectPaperPage:
    return ProjectPaperPage(
        items=[ProjectPaperSummaryResponse.model_construct(document_id=item_id)],
        positions=[ProjectPagePosition(key="2026-08-13T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def _output_page(*, item_id: UUID, has_more: bool) -> ProjectOutputPage:
    return ProjectOutputPage(
        items=[LibraryOutputResponse.model_construct()],
        positions=[ProjectPagePosition(key="2026-08-13T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def test_project_documents_cursor_survives_page_size_changes() -> None:
    """Page size is a preference, not a filter: the same keyset cursor must
    remain valid when the caller changes limit between document pages."""
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_documents.side_effect = [
        _paper_page(item_id=first_id, has_more=True),
        _paper_page(item_id=second_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)
    project_id = uuid4()

    first = projects.documents(
        actor=_actor(),
        project_id=project_id,
        load_urls=False,
        sort=ProjectPaperSort.ADDED_DESC,
        limit=1,
    )
    resized = projects.documents(
        actor=_actor(),
        project_id=project_id,
        load_urls=False,
        sort=ProjectPaperSort.ADDED_DESC,
        limit=50,
        cursor=first.next_cursor,
    )

    assert resized.total_count == 2
    assert gateway.list_documents.call_args_list[1].kwargs["position"].id == first_id
    assert gateway.list_documents.call_args_list[1].kwargs["limit"] == 50


def test_project_documents_cursor_is_bound_to_personal_filters() -> None:
    gateway = MagicMock()
    gateway.list_documents.return_value = _paper_page(
        item_id=uuid4(),
        has_more=True,
    )
    projects = _projects(gateway=gateway)
    project_id = uuid4()
    tag_id = uuid4()

    first = projects.documents(
        actor=_actor(),
        project_id=project_id,
        load_urls=False,
        personal_statuses=(PaperStatus.reading,),
        personal_tag_ids=(tag_id,),
        limit=1,
    )

    assert first.next_cursor is not None
    with pytest.raises(AppError, match="cursor") as raised:
        projects.documents(
            actor=_actor(),
            project_id=project_id,
            load_urls=False,
            personal_statuses=(PaperStatus.completed,),
            personal_tag_ids=(tag_id,),
            cursor=first.next_cursor,
            limit=1,
        )

    assert raised.value.code == "project_cursor_invalid"


def test_project_personal_filters_are_actor_scoped_before_counting() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []
    tag_id = uuid4()

    with patch("app.bootstrap.adapters.project_gateway.project_repository.get_access"):
        page = SqlAlchemyProjectGateway(
            db,
            invitation_tokens=ProjectInvitationTokenCodec(
                "project-pagination-test-secret-32-bytes"
            ),
        ).list_documents(
            actor=_actor(7),
            project_id=uuid4(),
            load_urls=False,
            query=None,
            personal_statuses=(PaperStatus.reading,),
            personal_tag_ids=(tag_id,),
            sort=ProjectPaperSort.PERSONAL_ACTIVITY_DESC,
            limit=20,
            direction=ProjectPageDirection.FORWARD,
            position=None,
        )

    assert page.total_count == 0
    count_sql = str(
        db.scalar.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    page_sql = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    for statement in (count_sql, page_sql):
        assert "library_papers.user_id = 7" in statement
        assert "library_papers.status IN ('reading')" in statement
        assert tag_id.hex in statement
        assert "paper_tags.user_id = 7" in statement


def test_project_outputs_cursor_survives_page_size_changes() -> None:
    """Page size is a preference, not a filter: the same keyset cursor must
    remain valid when the caller changes limit between output pages."""
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_outputs.side_effect = [
        _output_page(item_id=first_id, has_more=True),
        _output_page(item_id=second_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)
    project_id = uuid4()

    first = projects.outputs(
        actor=_actor(),
        project_id=project_id,
        sort=LibraryOutputSort.UPDATED_DESC,
        limit=1,
    )
    resized = projects.outputs(
        actor=_actor(),
        project_id=project_id,
        sort=LibraryOutputSort.UPDATED_DESC,
        limit=50,
        cursor=first.next_cursor,
    )

    assert resized.total_count == 2
    assert gateway.list_outputs.call_args_list[1].kwargs["position"].id == first_id
    assert gateway.list_outputs.call_args_list[1].kwargs["limit"] == 50


def test_project_list_uses_one_aggregate_projection_query() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []

    page = SqlAlchemyProjectGateway(
        db,
        invitation_tokens=ProjectInvitationTokenCodec(
            "project-pagination-test-secret-32-bytes"
        ),
    ).list_projects(
        user_id=7,
        query="retrieval",
        sort=ProjectSort.ACTIVITY_DESC,
        limit=20,
        direction=ProjectPageDirection.FORWARD,
        position=None,
    )

    assert page.items == []
    assert page.total_count == 0
    db.scalar.assert_called_once()
    db.execute.assert_called_once()
    statement = str(db.execute.call_args.args[0])
    assert "project_papers" in statement
    assert "conversations" in statement
    assert "research_items.audience_project_id" in statement
    assert "project_collaborators" in statement
