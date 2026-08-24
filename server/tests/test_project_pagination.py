from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
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
    ProjectCollaboratorResponse,
    ProjectPaperSort,
    ProjectPaperSummaryResponse,
    ProjectResponse,
    ProjectSort,
)
from app.modules.projects.application.projects import (
    ProjectOutputPage,
    ProjectMemberPage,
    ProjectMemberPagePosition,
    ProjectPage,
    ProjectPageDirection,
    ProjectPagePosition,
    ProjectPaperPage,
    ProjectResourcePreview,
    ProjectSummaryPage,
    Projects,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from sqlalchemy.dialects import postgresql
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


def _summary_page(*, item_id: UUID, has_more: bool) -> ProjectSummaryPage:
    return ProjectSummaryPage(
        items=[
            ProjectResourcePreview(
                value=ProjectResponse.model_construct(id=item_id),
                content_truncated=True,
            )
        ],
        positions=[ProjectPagePosition(key="2026-08-13T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def test_project_summary_cursor_reuses_full_collection_binding_and_gateway_plan() -> (
    None
):
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_projects.side_effect = AssertionError("full Project path must not run")
    gateway.list_project_summaries.side_effect = [
        _summary_page(item_id=first_id, has_more=True),
        _summary_page(item_id=second_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)

    first = projects.summary_list(actor=_actor(), query="graph", limit=1)
    assert first.value.next_cursor is not None
    assert first.content_truncated is True
    second = projects.summary_list(
        actor=_actor(),
        query="graph",
        cursor=first.value.next_cursor,
        limit=25,
    )

    assert second.value.previous_cursor is not None
    assert gateway.list_project_summaries.call_args_list[1].kwargs["position"].id == (
        first_id
    )
    assert gateway.list_project_summaries.call_args_list[1].kwargs["limit"] == 25
    gateway.list_projects.assert_not_called()


def _member_page(
    *,
    user_id: int,
    kind: str,
    has_more: bool,
) -> ProjectMemberPage:
    return ProjectMemberPage(
        items=[ProjectCollaboratorResponse.model_construct(user_id=user_id)],
        positions=[
            ProjectMemberPagePosition(
                kind=kind,
                key="" if kind == "owner" else "2026-08-13T10:00:00+00:00",
                user_id=user_id,
            )
        ],
        has_more=has_more,
        total_count=2,
    )


def _tamper(cursor: str) -> str:
    replacement = "A" if cursor[-1] != "A" else "B"
    return f"{cursor[:-1]}{replacement}"


def test_project_member_cursor_pages_and_allows_page_size_changes() -> None:
    gateway = MagicMock()
    gateway.list_members_page.side_effect = [
        _member_page(user_id=7, kind="owner", has_more=True),
        _member_page(user_id=8, kind="collaborator", has_more=False),
    ]
    projects = _projects(gateway=gateway)
    project_id = uuid4()

    first = projects.members_page(
        actor=_actor(),
        project_id=project_id,
        limit=1,
    )
    assert first.next_cursor is not None
    assert first.total_count == 2

    second = projects.members_page(
        actor=_actor(),
        project_id=project_id,
        cursor=first.next_cursor,
        limit=50,
    )
    assert second.next_cursor is None
    assert gateway.list_members_page.call_args_list[1].kwargs["limit"] == 50
    assert gateway.list_members_page.call_args_list[1].kwargs["position"] == (
        ProjectMemberPagePosition(kind="owner", key="", user_id=7)
    )


@pytest.mark.parametrize("binding_change", ["actor", "project", "tamper"])
def test_project_member_cursor_rejects_tamper_and_cross_scope_reuse(
    binding_change: str,
) -> None:
    gateway = MagicMock()
    gateway.list_members_page.return_value = _member_page(
        user_id=7,
        kind="owner",
        has_more=True,
    )
    projects = _projects(gateway=gateway)
    project_id = uuid4()
    first = projects.members_page(actor=_actor(), project_id=project_id, limit=1)
    assert first.next_cursor is not None
    actor = _actor(8) if binding_change == "actor" else _actor()
    requested_project_id = uuid4() if binding_change == "project" else project_id
    cursor = (
        _tamper(first.next_cursor) if binding_change == "tamper" else first.next_cursor
    )

    with pytest.raises(AppError, match="cursor") as raised:
        projects.members_page(
            actor=actor,
            project_id=requested_project_id,
            cursor=cursor,
            limit=50,
        )

    assert raised.value.code == "project_cursor_invalid"


def test_paper_project_cursor_pages_bidirectionally_and_allows_limit_changes() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list_projects_for_document.side_effect = [
        _page(item_id=first_id, has_more=True),
        _page(item_id=second_id, has_more=False),
        _page(item_id=first_id, has_more=False),
    ]
    projects = _projects(gateway=gateway)
    document_id = uuid4()

    first = projects.projects_for_document_page(
        actor=_actor(), document_id=document_id, limit=1
    )
    assert first.next_cursor is not None
    assert first.previous_cursor is None

    second = projects.projects_for_document_page(
        actor=_actor(),
        document_id=document_id,
        cursor=first.next_cursor,
        limit=25,
    )
    assert second.previous_cursor is not None
    assert gateway.list_projects_for_document.call_args_list[1].kwargs["limit"] == 25
    assert (
        gateway.list_projects_for_document.call_args_list[1].kwargs["direction"]
        is ProjectPageDirection.FORWARD
    )

    projects.projects_for_document_page(
        actor=_actor(),
        document_id=document_id,
        cursor=second.previous_cursor,
        limit=1,
    )
    assert (
        gateway.list_projects_for_document.call_args_list[2].kwargs["direction"]
        is ProjectPageDirection.BACKWARD
    )


@pytest.mark.parametrize("binding_change", ["actor", "document", "tamper"])
def test_paper_project_cursor_rejects_tamper_and_cross_scope_reuse(
    binding_change: str,
) -> None:
    gateway = MagicMock()
    gateway.list_projects_for_document.return_value = _page(
        item_id=uuid4(),
        has_more=True,
    )
    projects = _projects(gateway=gateway)
    document_id = uuid4()
    first = projects.projects_for_document_page(
        actor=_actor(), document_id=document_id, limit=1
    )
    assert first.next_cursor is not None
    actor = _actor(8) if binding_change == "actor" else _actor()
    requested_document_id = uuid4() if binding_change == "document" else document_id
    cursor = (
        _tamper(first.next_cursor) if binding_change == "tamper" else first.next_cursor
    )

    with pytest.raises(AppError, match="cursor") as raised:
        projects.projects_for_document_page(
            actor=actor,
            document_id=requested_document_id,
            cursor=cursor,
            limit=25,
        )

    assert raised.value.code == "project_cursor_invalid"


def test_project_member_gateway_uses_joined_at_and_user_id_keyset() -> None:
    db = MagicMock(spec=Session)
    project_id = uuid4()
    project = SimpleNamespace(
        id=project_id,
        owner_id=1,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    owner = SimpleNamespace(
        id=1,
        display_name="Owner",
        email="owner@example.com",
    )
    db.get.return_value = owner
    db.scalar.return_value = 4
    db.scalars.return_value.all.return_value = []

    with patch(
        "app.bootstrap.adapters.project_gateway.project_repository.get_access",
        return_value=SimpleNamespace(project=project),
    ):
        page = SqlAlchemyProjectGateway(
            db,
            invitation_tokens=ProjectInvitationTokenCodec(
                "project-pagination-test-secret-32-bytes"
            ),
        ).list_members_page(
            user_id=7,
            project_id=project_id,
            limit=2,
            position=ProjectMemberPagePosition(
                kind="collaborator",
                key="2026-08-13T10:00:00+00:00",
                user_id=8,
            ),
        )

    assert page.items == []
    assert page.total_count == 5
    statement = db.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "project_collaborators.joined_at >" in compiled
    assert "project_collaborators.user_id > 8" in compiled
    assert "ORDER BY scholens.project_collaborators.joined_at ASC" in compiled
    assert "scholens.project_collaborators.user_id ASC" in compiled
    assert "LIMIT 3" in compiled


def test_paper_project_gateway_applies_access_and_uuid_keyset_in_sql() -> None:
    db = MagicMock(spec=Session)
    document_id = uuid4()
    position_id = uuid4()
    db.scalar.return_value = 4
    db.scalars.return_value.all.return_value = []

    page = SqlAlchemyProjectGateway(
        db,
        invitation_tokens=ProjectInvitationTokenCodec(
            "project-pagination-test-secret-32-bytes"
        ),
    ).list_projects_for_document(
        actor=_actor(7),
        document_id=document_id,
        limit=2,
        direction=ProjectPageDirection.FORWARD,
        position=ProjectPagePosition(key=str(position_id), id=position_id),
    )

    assert page.items == []
    assert page.total_count == 4
    count_sql = str(
        db.scalar.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    page_sql = str(
        db.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    for statement in (count_sql, page_sql):
        assert document_id.hex in statement
        assert "projects.owner_id = 7" in statement
        assert "project_collaborators.user_id = 7" in statement
    assert f"projects.id > '{position_id.hex}'" in page_sql
    assert "ORDER BY scholens.projects.id ASC" in page_sql
    assert "LIMIT 3" in page_sql


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
        load_preview_urls=False,
        sort=ProjectPaperSort.ADDED_DESC,
        limit=1,
    )
    resized = projects.documents(
        actor=_actor(),
        project_id=project_id,
        load_urls=False,
        load_preview_urls=False,
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
        load_preview_urls=False,
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
            load_preview_urls=False,
            personal_statuses=(PaperStatus.completed,),
            personal_tag_ids=(tag_id,),
            cursor=first.next_cursor,
            limit=1,
        )

    assert raised.value.code == "project_cursor_invalid"


@pytest.mark.parametrize(
    ("changed_argument", "value"),
    [("load_urls", True), ("load_preview_urls", True)],
)
def test_project_documents_cursor_is_bound_to_url_loading_contract(
    changed_argument: str,
    value: bool,
) -> None:
    gateway = MagicMock()
    gateway.list_documents.return_value = _paper_page(
        item_id=uuid4(),
        has_more=True,
    )
    projects = _projects(gateway=gateway)
    project_id = uuid4()

    first = projects.documents(
        actor=_actor(),
        project_id=project_id,
        load_urls=False,
        load_preview_urls=False,
        limit=1,
    )
    arguments = {
        "actor": _actor(),
        "project_id": project_id,
        "load_urls": False,
        "load_preview_urls": False,
        "cursor": first.next_cursor,
        "limit": 1,
    }
    arguments[changed_argument] = value

    with pytest.raises(AppError, match="cursor") as raised:
        projects.documents(**arguments)

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
            load_preview_urls=False,
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


def test_project_paper_list_applies_literal_like_pattern_to_every_text_field() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []

    with patch("app.bootstrap.adapters.project_gateway.project_repository.get_access"):
        SqlAlchemyProjectGateway(
            db,
            invitation_tokens=ProjectInvitationTokenCodec(
                "project-pagination-test-secret-32-bytes"
            ),
        ).list_documents(
            actor=_actor(),
            project_id=uuid4(),
            load_urls=False,
            load_preview_urls=False,
            query="100%_\\",
            personal_statuses=(),
            personal_tag_ids=(),
            sort=ProjectPaperSort.ADDED_DESC,
            limit=20,
            direction=ProjectPageDirection.FORWARD,
            position=None,
        )

    statements = [db.scalar.call_args.args[0], db.execute.call_args.args[0]]
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.count(" LIKE ") == sql.count(" ESCAPE '\\\\'")
        assert "%100\\%\\_\\\\%" in compiled.params.values()


def test_project_document_urls_are_signed_only_when_independently_requested() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    document_id = uuid4()
    association_id = uuid4()
    now = datetime.now(timezone.utc)
    paper = SimpleNamespace(
        id=document_id,
        title="Preview contract",
        original_filename="preview-contract.pdf",
        abstract=None,
        authors=[],
        institutions=[],
        journal=None,
        publisher=None,
        doi=None,
        publish_date=None,
        s3_object_key="papers/original.pdf",
        preview_s3_key="previews/page-1.png",
        summary=None,
        keywords=[],
    )
    row = SimpleNamespace(
        Document=paper,
        LibraryPaper=SimpleNamespace(
            last_accessed_at=now,
            status=PaperStatus.completed,
            tags=[],
        ),
        ProjectPaper=SimpleNamespace(id=association_id, created_at=now),
    )
    db.execute.return_value.all.return_value = [row]
    gateway = SqlAlchemyProjectGateway(
        db,
        invitation_tokens=ProjectInvitationTokenCodec(
            "project-pagination-test-secret-32-bytes"
        ),
    )

    with (
        patch("app.bootstrap.adapters.project_gateway.project_repository.get_access"),
        patch(
            "app.bootstrap.adapters.project_gateway.s3_service.generate_presigned_urls",
            side_effect=lambda objects: {
                key: f"https://signed.example/{object_key}"
                for key, object_key in objects.items()
            },
        ) as sign,
    ):
        unsigned = gateway.list_documents(
            actor=_actor(),
            project_id=uuid4(),
            load_urls=False,
            load_preview_urls=False,
            query=None,
            personal_statuses=(),
            personal_tag_ids=(),
            sort=ProjectPaperSort.ADDED_DESC,
            limit=20,
            direction=ProjectPageDirection.FORWARD,
            position=None,
        )
        sign.assert_not_called()
        assert unsigned.items[0].file_url is None
        assert unsigned.items[0].preview_url is None
        assert unsigned.items[0].status == "reading"
        assert unsigned.items[0].personal_status is PaperStatus.completed

        preview_only = gateway.list_documents(
            actor=_actor(),
            project_id=uuid4(),
            load_urls=False,
            load_preview_urls=True,
            query=None,
            personal_statuses=(),
            personal_tag_ids=(),
            sort=ProjectPaperSort.ADDED_DESC,
            limit=20,
            direction=ProjectPageDirection.FORWARD,
            position=None,
        )

    sign.assert_called_once_with({str(document_id): "previews/page-1.png"})
    assert preview_only.items[0].file_url is None
    assert preview_only.items[0].preview_url == (
        "https://signed.example/previews/page-1.png"
    )


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


def test_project_outputs_accept_merge_base_projects_v1_cursor() -> None:
    project_id = uuid4()
    previous_id = uuid4()
    gateway = MagicMock()
    gateway.list_outputs.return_value = _output_page(
        item_id=uuid4(),
        has_more=False,
    )
    codec = SignedCursorCodec(
        "projects-test-secret",
        revision="projects-v1",
        error_code="project_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    filters = {
        "project_id": str(project_id),
        "q": "citation",
        "kinds": [],
        "sort": LibraryOutputSort.UPDATED_DESC.value,
    }
    fingerprint = json.dumps(
        {
            "revision": "projects-v1",
            "user_id": _actor().id,
            "collection": "project-outputs",
            "filters": filters,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    merge_base_cursor = codec.encode_keyset(
        fingerprint=fingerprint,
        values=("forward", "2026-08-13T10:00:00+00:00", str(previous_id)),
    )

    _projects(gateway=gateway).outputs(
        actor=_actor(),
        project_id=project_id,
        query="citation",
        cursor=merge_base_cursor,
        limit=100,
    )

    call = gateway.list_outputs.call_args.kwargs
    assert call["position"].id == previous_id
    assert call["direction"] is ProjectPageDirection.FORWARD
    assert call["limit"] == 100


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


def test_project_list_applies_literal_like_pattern_to_every_text_field() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []

    SqlAlchemyProjectGateway(
        db,
        invitation_tokens=ProjectInvitationTokenCodec(
            "project-pagination-test-secret-32-bytes"
        ),
    ).list_projects(
        user_id=7,
        query="100%_\\",
        sort=ProjectSort.ACTIVITY_DESC,
        limit=20,
        direction=ProjectPageDirection.FORWARD,
        position=None,
    )

    statements = [db.scalar.call_args.args[0], db.execute.call_args.args[0]]
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.count(" LIKE ") == sql.count(" ESCAPE '\\\\'")
        assert "%100\\%\\_\\\\%" in compiled.params.values()
