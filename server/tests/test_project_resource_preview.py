from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.bootstrap.adapters.project_gateway import SqlAlchemyProjectGateway
from app.modules.projects.application.contracts import ProjectPaperSort, ProjectSort
from app.modules.projects.application.projects import ProjectPageDirection
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def _gateway(db: Session) -> SqlAlchemyProjectGateway:
    return SqlAlchemyProjectGateway(db, invitation_tokens=MagicMock())


def _project_row(*, project_id: object, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        title="Bounded Project",
        description="Bounded description",
        owner_id=7,
        owner_display_name="Owner",
        owner_email="owner@example.com",
        can_edit_project=None,
        can_manage_papers=None,
        can_manage_collaborators=None,
        num_papers=3,
        num_conversations=2,
        num_outputs=1,
        num_collaborators=4,
        activity_at=now,
        created_at=now,
        updated_at=now,
        content_truncated=True,
    )


def test_project_resource_catalog_selects_only_bounded_ids_and_titles() -> None:
    project_id = uuid4()
    rows = MagicMock()
    rows.all.return_value = [SimpleNamespace(id=project_id, title="Bounded Project")]
    db = MagicMock(spec=Session)
    db.execute.return_value = rows

    items = _gateway(db).list_resource_catalog(user_id=7, limit=25)

    assert [(item.id, item.title) for item in items] == [
        (project_id, "Bounded Project")
    ]
    statement = db.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "title",
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(CAST(scholens.projects.title AS TEXT)" in sql
    assert "scholens.projects.description" not in sql


def test_project_resource_page_uses_bounded_scalar_projection_before_models() -> None:
    project_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    rows = MagicMock()
    rows.all.return_value = [_project_row(project_id=project_id, now=now)]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.return_value = rows

    page = _gateway(db).list_resource_projects(
        user_id=7,
        document_id=uuid4(),
        limit=25,
    )

    assert page.total_count == 1
    assert page.has_more is False
    assert page.items[0].value.id == project_id
    assert page.items[0].value.num_papers == 3
    assert page.items[0].content_truncated is True
    statement = db.execute.call_args.args[0]
    selected = tuple(column.key for column in statement.selected_columns)
    assert selected == (
        "id",
        "title",
        "description",
        "owner_id",
        "owner_display_name",
        "owner_email",
        "can_edit_project",
        "can_manage_papers",
        "can_manage_collaborators",
        "num_papers",
        "num_conversations",
        "num_outputs",
        "num_collaborators",
        "activity_at",
        "created_at",
        "updated_at",
        "content_truncated",
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(CAST(scholens.projects.description AS TEXT)" in sql
    assert "EXISTS (SELECT scholens.project_papers.id" in sql


def test_project_resource_papers_never_hydrate_document_arrays_or_text() -> None:
    project_id = uuid4()
    document_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    access_result = MagicMock()
    access_result.one_or_none.return_value = _project_row(
        project_id=project_id,
        now=now,
    )
    paper_results = MagicMock()
    paper_results.all.return_value = [
        SimpleNamespace(
            association_id=uuid4(),
            document_id=document_id,
            title="Bounded paper",
            added_at=now,
            abstract="Bounded abstract",
            journal=None,
            publisher=None,
            doi=None,
            publish_date=None,
            summary=None,
            library_entry_id=None,
            personal_status=None,
            personal_last_accessed_at=None,
            content_truncated=True,
        )
    ]
    db = MagicMock(spec=Session)
    db.execute.side_effect = [access_result, paper_results]
    db.scalar.return_value = 1

    page = _gateway(db).list_resource_documents(
        actor=SimpleNamespace(id=7),
        project_id=project_id,
        limit=10,
    )

    assert page.value.items[0].document_id == document_id
    assert page.value.items[0].authors is None
    assert page.value.items[0].keywords == []
    assert page.content_truncated is True
    statement = db.execute.call_args_list[1].args[0]
    selected = {column.key for column in statement.selected_columns}
    assert "abstract" in selected
    assert "summary" in selected
    assert selected.isdisjoint(
        {
            "authors",
            "institutions",
            "keywords",
            "raw_content",
            "summary_citations",
        }
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(CAST(scholens.documents.abstract AS TEXT)" in sql


def test_project_resource_members_select_only_bounded_identity_scalars() -> None:
    project_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    access_result = MagicMock()
    access_result.one_or_none.return_value = _project_row(
        project_id=project_id,
        now=now,
    )
    member_results = MagicMock()
    member_results.all.return_value = [
        SimpleNamespace(
            user_id=8,
            display_name="Collaborator",
            email="collaborator@example.com",
            can_edit_project=True,
            can_manage_papers=False,
            can_manage_collaborators=False,
            joined_at=now,
            content_truncated=False,
        )
    ]
    db = MagicMock(spec=Session)
    db.execute.side_effect = [access_result, member_results]
    db.scalar.return_value = 1

    page = _gateway(db).list_resource_members(
        user_id=7,
        project_id=project_id,
        limit=50,
    )

    assert [item.user_id for item in page.value.items] == [7, 8]
    assert page.value.total_count == 2
    statement = db.execute.call_args_list[1].args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "user_id",
        "display_name",
        "email",
        "can_edit_project",
        "can_manage_papers",
        "can_manage_collaborators",
        "joined_at",
        "content_truncated",
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(CAST(coalesce(" in sql


def test_project_tool_summary_preserves_list_plan_without_orm_hydration() -> None:
    project_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    row = _project_row(project_id=project_id, now=now)
    row.description = "\\" * 512
    row.content_truncated = False
    results = MagicMock()
    results.all.return_value = [row]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.return_value = results

    page = _gateway(db).list_project_summaries(
        user_id=7,
        query="bounded",
        sort=ProjectSort.ACTIVITY_DESC,
        limit=25,
        direction=ProjectPageDirection.FORWARD,
        position=None,
    )

    assert page.items[0].content_truncated is True
    assert len(page.items[0].value.description or "") < len(row.description)
    statement = db.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "title",
        "description",
        "owner_id",
        "owner_display_name",
        "owner_email",
        "can_edit_project",
        "can_manage_papers",
        "can_manage_collaborators",
        "num_papers",
        "num_conversations",
        "num_outputs",
        "num_collaborators",
        "activity_at",
        "created_at",
        "updated_at",
        "content_truncated",
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "SELECT scholens.projects" in sql
    assert "FROM scholens.projects" in sql
    assert "scholens.projects.description AS description" not in sql


def test_project_paper_tool_summary_selects_no_full_text_arrays_or_tags() -> None:
    project_id = uuid4()
    document_id = uuid4()
    association_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    access_result = MagicMock()
    access_result.one_or_none.return_value = _project_row(
        project_id=project_id,
        now=now,
    )
    paper_result = MagicMock()
    paper_result.all.return_value = [
        SimpleNamespace(
            association_id=association_id,
            document_id=document_id,
            title="\\" * 256,
            added_at=now,
            abstract="bounded abstract",
            journal=None,
            publisher=None,
            doi=None,
            publish_date=None,
            summary=None,
            library_entry_id=None,
            personal_status=None,
            personal_last_accessed_at=None,
            content_truncated=False,
        )
    ]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.side_effect = [access_result, paper_result]

    page = _gateway(db).list_document_summaries(
        actor=SimpleNamespace(id=7),
        project_id=project_id,
        query="paper",
        personal_statuses=(),
        personal_tag_ids=(),
        sort=ProjectPaperSort.TITLE_ASC,
        limit=10,
        direction=ProjectPageDirection.FORWARD,
        position=None,
    )

    assert page.content_truncated is True
    assert page.items[0].authors is None
    assert page.items[0].personal_tags == []
    statement = db.execute.call_args_list[1].args[0]
    selected = {column.key for column in statement.selected_columns}
    assert selected.isdisjoint(
        {
            "authors",
            "institutions",
            "keywords",
            "raw_content",
            "summary_citations",
            "metadata_overrides",
            "tags",
        }
    )
    assert {"association_id", "content_truncated"} <= selected
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "left(CAST(scholens.documents.title AS TEXT)" in sql


def test_paper_project_tool_summary_uses_bounded_project_statement() -> None:
    project_id = uuid4()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    results = MagicMock()
    results.all.return_value = [_project_row(project_id=project_id, now=now)]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 1
    db.execute.return_value = results

    page = _gateway(db).list_project_summaries_for_document(
        actor=SimpleNamespace(id=7),
        document_id=uuid4(),
        limit=25,
        direction=ProjectPageDirection.FORWARD,
        position=None,
    )

    assert page.items[0].value.id == project_id
    statement = db.execute.call_args.args[0]
    selected = tuple(column.key for column in statement.selected_columns)
    assert selected[0:3] == ("id", "title", "description")
    assert "Project" not in selected
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "JOIN scholens.project_papers" in sql
    assert "left(CAST(scholens.projects.description AS TEXT)" in sql
