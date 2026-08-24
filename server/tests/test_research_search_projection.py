from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.bootstrap.adapters.research_search import (
    RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT,
    RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD,
    SqlResearchSearch,
)
from app.modules.research.application.search import (
    ResearchSearchQuery,
    ResearchSearchResponse,
    ResearchSearchPosition,
    ResearchSearchScope,
    SearchResearch,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import FailureKind
from app.shared.infrastructure.sql_patterns import literal_contains_pattern
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _mapping_result(rows: list[dict[str, object]]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def test_candidate_page_uses_count_free_keyset_and_limit_plus_one() -> None:
    port = MagicMock()
    port.search.return_value = ResearchSearchResponse(items=[], total=0)
    search = SearchResearch(
        port,
        SignedCursorCodec(
            "research-search-candidate-test",
            revision="research-search-test:1",
            error_code="research_search_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
    )
    scope = ResearchSearchScope.project(UUID(int=500))
    after = ResearchSearchPosition(
        created_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
        item_id=UUID(int=42),
    )

    page = search.candidate_page(
        actor=_actor(),
        query="  literal match  ",
        limit=25,
        scope=scope,
        after=after,
    )

    assert page.items == ()
    assert page.has_more is False
    request = port.search.call_args.kwargs["request"]
    assert request.query == "literal match"
    assert request.limit == 26
    assert request.offset == 0
    assert request.include_total is False
    assert request.scope == scope
    assert request.after == after


def _compile(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


def test_research_search_projects_bounded_scalars_and_comments_in_sql() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    thread_id = UUID(int=1)
    document_id = UUID(int=2)
    db = MagicMock()
    db.scalar.return_value = 1
    db.execute.side_effect = [
        _mapping_result(
            [
                {
                    "thread_id": thread_id,
                    "document_id": document_id,
                    "project_id": None,
                    "document_title": "Paper",
                    "quote_text": "bounded quote",
                    "position": None,
                    "role": "assistant",
                    "created_at": now,
                }
            ]
        ),
        _mapping_result(
            [
                {
                    "comment_id": UUID(int=index + 10),
                    "thread_id": thread_id,
                    "content": f"matching comment {index}",
                    "role": "user",
                    "created_at": now + timedelta(seconds=index),
                    "thread_rank": index + 1,
                }
                for index in range(3)
            ]
        ),
    ]

    query = "matching%_" + "\\" + "literal"
    response = SqlResearchSearch(db).search(
        actor=_actor(),
        request=ResearchSearchQuery(query=query, limit=25, offset=0),
    )

    assert response.total == 1
    assert [comment.content for comment in response.items[0].matching_comments] == [
        "matching comment 0",
        "matching comment 1",
        "matching comment 2",
    ]
    thread_sql = _compile(db.execute.call_args_list[0].args[0])
    comment_sql = _compile(db.execute.call_args_list[1].args[0])
    count_sql = _compile(db.scalar.call_args.args[0])
    expected_pattern = literal_contains_pattern(query.casefold())
    for call in (*db.execute.call_args_list, db.scalar.call_args):
        bound = call.args[0].compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
        )
        assert expected_pattern in bound.params.values()
    assert "research_items.*" not in thread_sql
    assert "annotation_comments.*" not in comment_sql
    assert "left(" in thread_sql
    assert "left(" in comment_sql
    assert "row_number() over" in comment_sql
    assert "ranked_matching_comments.thread_rank <= 3" in comment_sql
    assert "limit 200" in comment_sql
    assert "research_items.created_at desc" in thread_sql
    assert "project_collaborators" in thread_sql
    assert "escape '\\\\'" in thread_sql
    assert "escape '\\\\'" in comment_sql
    assert "select scholens.research_items.id" in count_sql
    assert "research_items.*" not in count_sql


def test_research_search_defensively_bounds_hostile_fake_rows() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    hostile = '\x00"\\😀' * 10_000
    thread_rows = [
        {
            "thread_id": UUID(int=index + 1),
            "document_id": UUID(int=1_000 + index),
            "project_id": None,
            "document_title": hostile,
            "quote_text": hostile,
            "position": None,
            "role": "assistant",
            "created_at": now - timedelta(seconds=index),
        }
        for index in range(100)
    ]
    comment_rows = [
        {
            "comment_id": UUID(int=10_000 + thread_index * 4 + rank),
            "thread_id": UUID(int=thread_index + 1),
            "content": hostile,
            "role": "user",
            "created_at": now + timedelta(seconds=rank),
            "thread_rank": rank + 1,
        }
        for rank in range(4)
        for thread_index in range(100)
    ]
    db = MagicMock()
    db.scalar.return_value = 100
    db.execute.side_effect = [
        _mapping_result(thread_rows),
        _mapping_result(comment_rows),
    ]

    response = SqlResearchSearch(db).search(
        actor=_actor(),
        request=ResearchSearchQuery(
            query="needle",
            limit=100,
            offset=0,
            include_total=False,
        ),
    )

    comments = [
        comment for item in response.items for comment in item.matching_comments
    ]
    assert len(response.items) == 100
    assert len(comments) == RESEARCH_SEARCH_MATCHING_COMMENTS_GLOBAL_LIMIT
    assert all(
        len(item.matching_comments) <= RESEARCH_SEARCH_MATCHING_COMMENTS_PER_THREAD
        for item in response.items
    )
    assert all(len(item.quote_text.encode("utf-8")) <= 900 for item in response.items)
    assert all(len(comment.content.encode("utf-8")) <= 900 for comment in comments)
    assert len(response.model_dump_json().encode("utf-8")) < 512 * 1_024
    db.scalar.assert_not_called()


@pytest.mark.parametrize(
    ("scope", "required_sql"),
    [
        (
            ResearchSearchScope.personal_library(),
            ("library_papers", "research_items.created_by_id = 7"),
        ),
        (
            ResearchSearchScope.project(UUID(int=500)),
            ("research_items.audience_project_id", "'project'"),
        ),
        (
            ResearchSearchScope.paper(UUID(int=600), project_id=UUID(int=500)),
            (
                "research_items.target_document_id",
                "research_items.audience_project_id",
            ),
        ),
    ],
)
def test_scope_filter_precedes_candidate_limit_so_cross_scope_noise_cannot_starve(
    scope: ResearchSearchScope,
    required_sql: tuple[str, ...],
) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    db = MagicMock()
    db.execute.side_effect = [
        _mapping_result(
            [
                {
                    "thread_id": UUID(int=1),
                    "document_id": UUID(int=600),
                    "project_id": scope.project_id,
                    "document_title": "Target after 100 cross-scope matches",
                    "quote_text": "needle",
                    "position": None,
                    "role": "assistant",
                    "created_at": now,
                }
            ]
        ),
        _mapping_result([]),
    ]

    response = SqlResearchSearch(db).search(
        actor=_actor(),
        request=ResearchSearchQuery(
            query="needle",
            limit=25,
            offset=0,
            include_total=False,
            scope=scope,
        ),
    )

    sql = _compile(db.execute.call_args_list[0].args[0])
    assert [item.id for item in response.items] == [UUID(int=1)]
    assert "limit 25" in sql
    for fragment in required_sql:
        assert fragment in sql
        assert sql.index(fragment) < sql.index("limit 25")


def test_research_candidate_keyset_is_applied_before_the_bounded_window() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    db = MagicMock()
    db.execute.side_effect = [_mapping_result([]), _mapping_result([])]

    SqlResearchSearch(db).search(
        actor=_actor(),
        request=ResearchSearchQuery(
            query="needle",
            limit=26,
            offset=0,
            include_total=False,
            scope=ResearchSearchScope.all_accessible(),
            after=ResearchSearchPosition(created_at=now, item_id=UUID(int=99)),
        ),
    )

    sql = _compile(db.execute.call_args_list[0].args[0])
    assert "research_items.created_at <" in sql
    assert "research_items.created_at =" in sql
    assert "research_items.id >" in sql
    assert sql.index("research_items.created_at <") < sql.index("limit 26")
