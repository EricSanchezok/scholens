from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from app.bootstrap.adapters.research_output_catalog import (
    SqlAlchemyResearchOutputCatalog,
)
from app.modules.research.application.catalog import (
    ResearchOutputCatalog,
    ResearchOutputCatalogScope,
    ResearchOutputCatalogSort,
    ResearchOutputPageDirection,
    ResearchOutputPagePosition,
    ResearchOutputSummaryPage,
)
from app.modules.research.application.contracts import (
    PersonalResearchAudience,
    ResearchOutputCreatorSummary,
    ResearchOutputSourceSummary,
    ResearchOutputSummary,
    ResearchOutputSummaryListResponse,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind
from app.shared.infrastructure.sql_patterns import literal_contains_pattern
from app.tooling import ToolOutcome, ToolResourceLink, serialize_tool_success
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _summary(*, item_id: UUID, title: str = "Bounded output") -> ResearchOutputSummary:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    return ResearchOutputSummary(
        item_id=item_id,
        kind=ResearchItemKind.ANNOTATION_THREAD,
        audience=PersonalResearchAudience(),
        target_document_id=uuid4(),
        title=title,
        excerpt="A bounded excerpt",
        creator=ResearchOutputCreatorSummary(id=7, display_name="Researcher"),
        created_at=now - timedelta(minutes=1),
        updated_at=now,
        source=ResearchOutputSourceSummary(
            audience_type=ResearchAudienceType.PERSONAL,
            audience_id=None,
            title="Personal Library",
        ),
        resource_uri=f"scholens://annotation-threads/{item_id}",
    )


def _catalog(gateway: MagicMock) -> ResearchOutputCatalog:
    return ResearchOutputCatalog(
        gateway,
        cursors=SignedCursorCodec(
            "research-output-catalog-test-secret",
            revision="research-output-catalog-v1",
            error_code="research_output_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
    )


def _page(*, item_id: UUID, has_more: bool) -> ResearchOutputSummaryPage:
    item = _summary(item_id=item_id)
    return ResearchOutputSummaryPage(
        items=[item],
        positions=[
            ResearchOutputPagePosition(key=item.updated_at.isoformat(), item_id=item_id)
        ],
        has_more=has_more,
        total_count=2,
    )


@pytest.mark.parametrize(
    "scope",
    [
        ResearchOutputCatalogScope.library(),
        ResearchOutputCatalogScope.project(uuid4()),
        ResearchOutputCatalogScope.paper(uuid4()),
    ],
)
def test_catalog_passes_every_scope_to_one_bounded_gateway(
    scope: ResearchOutputCatalogScope,
) -> None:
    gateway = MagicMock()
    gateway.list.return_value = ResearchOutputSummaryPage(
        items=[],
        positions=[],
        has_more=False,
        total_count=0,
    )

    response = _catalog(gateway).list(
        actor=_actor(),
        scope=scope,
        query="  Graph Evidence  ",
        kinds=(ResearchItemKind.CITATION,),
        limit=25,
    )

    assert response.items == []
    assert response.total_count == 0
    assert gateway.list.call_args.kwargs["scope"] == scope
    assert gateway.list.call_args.kwargs["query"] == "graph evidence"
    assert gateway.list.call_args.kwargs["limit"] == 25
    assert gateway.list.call_args.kwargs["include_total_count"] is True


def test_catalog_candidate_page_passes_forward_keyset_without_count() -> None:
    item = _summary(item_id=uuid4())
    after = ResearchOutputPagePosition(
        key=item.updated_at.isoformat(),
        item_id=item.item_id,
    )
    expected = ResearchOutputSummaryPage(
        items=[item],
        positions=[after],
        has_more=True,
        total_count=None,
    )
    gateway = MagicMock()
    gateway.list.return_value = expected

    result = _catalog(gateway).candidate_page(
        actor=_actor(),
        scope=ResearchOutputCatalogScope.personal_library(),
        query="  Graph Evidence  ",
        kinds=(ResearchItemKind.DATA_TABLE, ResearchItemKind.CITATION),
        limit=25,
        after=after,
    )

    assert result is expected
    call = gateway.list.call_args.kwargs
    assert call["query"] == "graph evidence"
    assert call["kinds"] == (
        ResearchItemKind.CITATION,
        ResearchItemKind.DATA_TABLE,
    )
    assert call["direction"] is ResearchOutputPageDirection.FORWARD
    assert call["position"] == after
    assert call["include_total_count"] is False


def test_catalog_get_delegates_one_authorized_bounded_lookup() -> None:
    item = _summary(item_id=uuid4())
    gateway = MagicMock()
    gateway.get.return_value = item

    result = _catalog(gateway).get(actor=_actor(), item_id=item.item_id)

    assert result == item
    gateway.get.assert_called_once_with(user_id=7, item_id=item.item_id)


def test_catalog_keyset_cursor_supports_previous_and_page_size_changes() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    gateway.list.side_effect = [
        _page(item_id=first_id, has_more=True),
        _page(item_id=second_id, has_more=False),
        _page(item_id=first_id, has_more=False),
    ]
    catalog = _catalog(gateway)
    scope = ResearchOutputCatalogScope.library()

    first = catalog.list(actor=_actor(), scope=scope, query="graph", limit=1)
    assert first.next_cursor is not None
    assert first.previous_cursor is None

    second = catalog.list(
        actor=_actor(),
        scope=scope,
        query="graph",
        cursor=first.next_cursor,
        limit=25,
    )
    assert second.previous_cursor is not None
    assert second.next_cursor is None
    assert gateway.list.call_args_list[1].kwargs["limit"] == 25
    assert gateway.list.call_args_list[1].kwargs["position"].item_id == first_id

    previous = catalog.list(
        actor=_actor(),
        scope=scope,
        query="graph",
        cursor=second.previous_cursor,
        limit=7,
    )
    assert previous.next_cursor is not None
    assert gateway.list.call_args_list[2].kwargs["direction"] is (
        ResearchOutputPageDirection.BACKWARD
    )


@pytest.mark.parametrize(
    ("actor", "query"),
    [(_actor(8), "graph"), (_actor(), "different")],
)
def test_catalog_cursor_is_bound_to_actor_and_query(actor: Actor, query: str) -> None:
    gateway = MagicMock()
    gateway.list.return_value = _page(item_id=uuid4(), has_more=True)
    catalog = _catalog(gateway)
    scope = ResearchOutputCatalogScope.library()
    first = catalog.list(actor=_actor(), scope=scope, query="graph", limit=1)

    with pytest.raises(AppError) as raised:
        catalog.list(
            actor=actor,
            scope=scope,
            query=query,
            cursor=first.next_cursor,
            limit=25,
        )

    assert raised.value.code == "research_output_cursor_invalid"


def _projection_rows() -> list[dict[str, object]]:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    document_id = uuid4()
    project_id = uuid4()
    rows: list[dict[str, object]] = []
    for index, kind in enumerate(ResearchItemKind):
        item_id = uuid4()
        audience_type = (
            ResearchAudienceType.PERSONAL
            if kind is ResearchItemKind.ANNOTATION_THREAD
            else (
                ResearchAudienceType.PROJECT
                if kind is ResearchItemKind.AUDIO_OVERVIEW
                else ResearchAudienceType.DOCUMENT
            )
        )
        rows.append(
            {
                "item_id": item_id,
                "kind": kind.value,
                "audience_type": audience_type.value,
                "audience_document_id": (
                    document_id
                    if audience_type is ResearchAudienceType.DOCUMENT
                    else None
                ),
                "audience_project_id": (
                    project_id
                    if audience_type is ResearchAudienceType.PROJECT
                    else None
                ),
                "target_document_id": document_id,
                "creator_id": 7,
                "creator_display_name": "Researcher",
                "created_at": now - timedelta(minutes=index + 1),
                "updated_at": now - timedelta(minutes=index),
                "title": f"Output {index}",
                "excerpt": f"Excerpt {index}",
                "source_title": "Source",
                "sort_key": now - timedelta(minutes=index),
            }
        )
    return rows


class _PoisonHugeCitationSnapshot:
    def __getitem__(self, _key: object) -> object:
        raise AssertionError("the full citation snapshot must not be consumed")

    def __iter__(self):
        raise AssertionError("the full citation snapshot must not be consumed")

    def __str__(self) -> str:
        raise AssertionError("the full citation snapshot must not be consumed")


def _adapter_session(rows: list[dict[str, object]]) -> MagicMock:
    db = MagicMock()
    db.scalar.return_value = len(rows)
    db.execute.return_value.mappings.return_value.all.return_value = rows
    return db


def test_sql_catalog_projects_all_four_kinds_without_hydrating_large_payloads() -> None:
    rows = _projection_rows()
    db = _adapter_session(rows)

    query = "needle%_" + "\\" + "literal"
    with patch(
        "app.bootstrap.adapters.research_repository.s3_service.generate_presigned_url"
    ) as sign_audio:
        response = SqlAlchemyResearchOutputCatalog(db).list(
            user_id=7,
            scope=ResearchOutputCatalogScope.library(),
            query=query,
            kinds=(),
            sort=ResearchOutputCatalogSort.UPDATED_DESC,
            limit=20,
            direction=ResearchOutputPageDirection.FORWARD,
            position=None,
        )

    assert [item.kind for item in response.items] == list(ResearchItemKind)
    assert all(len(item.title) <= 240 for item in response.items)
    assert all(len(item.excerpt) <= 1_200 for item in response.items)
    sign_audio.assert_not_called()

    statement = db.execute.call_args.args[0]
    bound = statement.compile(
        dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "annotation_comments" in sql
    assert "research_audio_overviews.transcript" in sql
    assert "research_audio_overviews.s3_object_key" not in sql
    assert "research_data_tables.rows" in sql
    assert "research_data_tables.citations" in sql
    assert "research_data_tables.row_failures" in sql
    assert "jsonb_path_query_array" not in sql
    assert "project_collaborators" in sql
    assert "research_items.*" not in sql
    assert "left(" in sql
    assert literal_contains_pattern(query) in bound.params.values()


def test_table_json_sql_producers_bound_huge_projection_and_stream_full_search() -> (
    None
):
    projection_sql = str(
        select(SqlAlchemyResearchOutputCatalog._table_text_expression()).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    search_sql = str(
        select(
            SqlAlchemyResearchOutputCatalog._table_search_predicate("%needle%")
        ).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "jsonb_path_query_array" not in projection_sql
    assert projection_sql.count("jsonb_path_query(") == 3
    assert projection_sql.count("limit 64") == 3
    assert "limit 32" in projection_sql
    assert "left(cast(" in projection_sql
    assert "as table_row_scalars(value)" in projection_sql
    assert "jsonb_path_query_array" not in search_sql
    assert search_sql.count("jsonb_path_query(") == 3
    assert search_sql.count("exists (select 1") == 4
    assert " limit " not in search_sql
    assert "as search_table_rows(value)" in search_sql
    for field in ("rows", "citations", "row_failures", "columns"):
        assert f"research_data_tables.{field}" in search_sql


def test_citation_sql_bounds_excerpt_and_streams_author_search() -> None:
    projection_sql = str(
        select(SqlAlchemyResearchOutputCatalog._citation_text_expression()).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    search_sql = str(
        select(
            SqlAlchemyResearchOutputCatalog._citation_search_predicate("%needle%")
        ).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "jsonb_path_query_array" not in projection_sql
    assert projection_sql.count("jsonb_path_query(") == 1
    assert "as citation_author_scalars(value)" in projection_sql
    assert "limit 1200" in projection_sql
    assert "left(cast(citation_author_scalars.value as text), 1200)" in projection_sql
    assert "string_agg(bounded_citation_author_scalars.value" in projection_sql
    assert "left(concat(" in projection_sql
    assert projection_sql.count(", 1200)") >= 9

    assert "jsonb_path_query_array" not in search_sql
    assert "string_agg" not in search_sql
    assert "concat_ws" not in search_sql
    assert search_sql.count("jsonb_path_query(") == 1
    assert "exists (select 1" in search_sql
    assert "as search_citation_authors(value)" in search_sql
    assert " limit " not in search_sql
    for field in (
        "title",
        "publish_date",
        "journal",
        "publisher",
        "doi",
        "preferred_style",
        "style_display",
    ):
        assert f"'{field}'" in search_sql


def test_citation_catalog_never_consumes_hostile_huge_author_snapshot() -> None:
    hostile = '\x00\\"中🙂' * 20_000
    row = next(
        item
        for item in _projection_rows()
        if item["kind"] == ResearchItemKind.CITATION.value
    )
    row.update(
        {
            "title": hostile,
            "excerpt": hostile,
            "snapshot": _PoisonHugeCitationSnapshot(),
        }
    )
    db = _adapter_session([row])
    db.scalars.side_effect = AssertionError(
        "the catalog must not hydrate full citation ORM rows"
    )

    page = SqlAlchemyResearchOutputCatalog(db).list(
        user_id=7,
        scope=ResearchOutputCatalogScope.library(),
        query=None,
        kinds=(ResearchItemKind.CITATION,),
        sort=ResearchOutputCatalogSort.UPDATED_DESC,
        limit=1,
        direction=ResearchOutputPageDirection.FORWARD,
        position=None,
    )

    assert len(page.items) == 1
    assert len(page.items[0].title.encode("utf-8")) <= 384
    assert len(page.items[0].excerpt.encode("utf-8")) <= 900
    db.scalars.assert_not_called()
    statement = db.execute.call_args.args[0]
    assert "snapshot" not in {column.key for column in statement.selected_columns}


def test_sql_catalog_get_selects_one_bounded_projection_by_authorized_id() -> None:
    row = _projection_rows()[0]
    db = MagicMock()
    db.execute.return_value.mappings.return_value.one_or_none.return_value = row

    result = SqlAlchemyResearchOutputCatalog(db).get(
        user_id=7,
        item_id=row["item_id"],
    )

    assert result.item_id == row["item_id"]
    statement = db.execute.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "research_items.*" not in sql
    assert "left(" in sql
    assert "project_collaborators" in sql


def test_emoji_heavy_maximum_page_stays_below_default_mcp_budget() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    document_id = uuid4()
    rows: list[dict[str, object]] = [
        {
            "item_id": uuid4(),
            "kind": ResearchItemKind.CITATION.value,
            "audience_type": ResearchAudienceType.DOCUMENT.value,
            "audience_document_id": document_id,
            "audience_project_id": None,
            "target_document_id": document_id,
            "creator_id": 7,
            "creator_display_name": "🧪" * 320,
            "created_at": now,
            "updated_at": now,
            "title": "🧪" * 240,
            "excerpt": "🧪" * 1_200,
            "source_title": "🧪" * 240,
            "sort_key": now,
        }
        for _ in range(25)
    ]
    db = _adapter_session(rows)
    page = SqlAlchemyResearchOutputCatalog(db).list(
        user_id=7,
        scope=ResearchOutputCatalogScope.library(),
        query=None,
        kinds=(),
        sort=ResearchOutputCatalogSort.UPDATED_DESC,
        limit=25,
        direction=ResearchOutputPageDirection.FORWARD,
        position=None,
    )
    payload = ResearchOutputSummaryListResponse(
        items=page.items,
        total_count=page.total_count,
    ).model_dump(mode="json")
    links = tuple(
        ToolResourceLink(
            uri=item.resource_uri,
            name=f"Research output {item.item_id}",
            description="Stored bounded research output.",
        )
        for item in page.items
    )
    serialized = serialize_tool_success(
        ToolOutcome(payload=payload, resource_links=links)
    )

    assert len(page.items) == 25
    assert all(len(item.title.encode("utf-8")) <= 480 for item in page.items)
    assert all(len(item.excerpt.encode("utf-8")) <= 1_200 for item in page.items)
    assert all(
        item.creator.display_name is not None
        and len(item.creator.display_name.encode("utf-8")) <= 640
        for item in page.items
    )
    assert all(len(item.source.title.encode("utf-8")) <= 480 for item in page.items)
    assert serialized.call_tool_result_utf8_bytes < 200 * 1_024


def test_json_escape_heavy_maximum_page_stays_below_default_mcp_budget() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    document_id = uuid4()
    hostile = '\x00\x01"\\' * 400
    rows: list[dict[str, object]] = [
        {
            "item_id": uuid4(),
            "kind": ResearchItemKind.CITATION.value,
            "audience_type": ResearchAudienceType.DOCUMENT.value,
            "audience_document_id": document_id,
            "audience_project_id": None,
            "target_document_id": document_id,
            "creator_id": 7,
            "creator_display_name": hostile,
            "created_at": now,
            "updated_at": now,
            "title": hostile,
            "excerpt": hostile,
            "source_title": hostile,
            "sort_key": now,
        }
        for _ in range(25)
    ]
    page = SqlAlchemyResearchOutputCatalog(_adapter_session(rows)).list(
        user_id=7,
        scope=ResearchOutputCatalogScope.library(),
        query=None,
        kinds=(),
        sort=ResearchOutputCatalogSort.UPDATED_DESC,
        limit=25,
        direction=ResearchOutputPageDirection.FORWARD,
        position=None,
    )
    payload = ResearchOutputSummaryListResponse(
        items=page.items,
        total_count=page.total_count,
    ).model_dump(mode="json")

    links = tuple(
        ToolResourceLink(
            uri=item.resource_uri,
            name=f"Research output {item.item_id}",
            description="Stored bounded research output.",
        )
        for item in page.items
    )
    serialized = serialize_tool_success(
        ToolOutcome(payload=payload, resource_links=links)
    )

    assert len(page.items) == 25
    assert serialized.call_tool_result_utf8_bytes < 200 * 1_024


def test_project_scope_authorizes_before_its_exact_audience_query() -> None:
    project_id = uuid4()
    db = _adapter_session([])

    with patch(
        "app.bootstrap.adapters.research_output_catalog.require_project_access"
    ) as require_access:
        SqlAlchemyResearchOutputCatalog(db).list(
            user_id=7,
            scope=ResearchOutputCatalogScope.project(project_id),
            query=None,
            kinds=(),
            sort=ResearchOutputCatalogSort.TITLE_ASC,
            limit=20,
            direction=ResearchOutputPageDirection.FORWARD,
            position=None,
        )

    require_access.assert_called_once_with(db, project_id=project_id, user_id=7)
    sql = str(db.execute.call_args.args[0]).lower()
    assert "research_items.audience_project_id" in sql
    assert "research_items.audience_type" in sql


def test_personal_library_scope_is_filtered_in_sql_without_hydration_or_count() -> None:
    db = _adapter_session([])

    page = SqlAlchemyResearchOutputCatalog(db).list(
        user_id=7,
        scope=ResearchOutputCatalogScope.personal_library(),
        query="needle",
        kinds=(ResearchItemKind.DATA_TABLE,),
        sort=ResearchOutputCatalogSort.UPDATED_DESC,
        limit=25,
        direction=ResearchOutputPageDirection.FORWARD,
        position=None,
        include_total_count=False,
    )

    statement = db.execute.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "library_papers" in sql
    assert "research_items.created_by_id = 7" in sql
    assert "research_items.target_document_id" in sql
    assert "research_items.audience_document_id" in sql
    assert "research_items.*" not in sql
    assert page.total_count is None
    db.scalar.assert_not_called()


def test_paper_scope_authorizes_the_exact_project_document_association() -> None:
    document_id = uuid4()
    project_id = uuid4()
    db = _adapter_session([])

    with patch(
        "app.bootstrap.adapters.research_output_catalog.require_document_access"
    ) as require_access:
        SqlAlchemyResearchOutputCatalog(db).list(
            user_id=7,
            scope=ResearchOutputCatalogScope.paper(
                document_id,
                project_id=project_id,
            ),
            query=None,
            kinds=(),
            sort=ResearchOutputCatalogSort.UPDATED_DESC,
            limit=20,
            direction=ResearchOutputPageDirection.FORWARD,
            position=None,
        )

    require_access.assert_called_once_with(
        db,
        document_id=document_id,
        user_id=7,
        project_id=project_id,
    )
    sql = str(db.execute.call_args.args[0]).lower()
    assert "research_items.target_document_id" in sql
    assert "research_items.audience_project_id" in sql
