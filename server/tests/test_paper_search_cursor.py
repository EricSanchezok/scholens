from datetime import UTC, datetime
from typing import Callable
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from app.bootstrap.adapters.paper_search import (
    PostgresPaperSearch,
    _SearchRanking,
    _compact_query,
    _visibility_condition,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    PersonalLibraryPaperCollection,
    PaperSearchCandidate,
    PaperSearchCandidatePage,
    PaperSearchFilters,
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSearchSort,
    PaperSearchStats,
    SelectedPaperCollection,
)
from app.modules.papers.application.search import SearchCursorCodec, SearchPapers
from app.shared.application import Actor
from app.shared.domain.enums import PaperStatus
from app.shared.domain import AppError, FailureKind
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _paper() -> PaperSearchResult:
    now = datetime.now(UTC)
    return PaperSearchResult(
        document_id=uuid4(),
        title="Search result",
        authors=[],
        abstract=None,
        status="completed",
        publish_date=None,
        created_at=now,
        last_accessed_at=now,
    )


class _SearchBackend:
    def __init__(self) -> None:
        self.requests: list[PaperSearchQuery] = []

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse:
        self.requests.append(request)
        return PaperSearchResponse(
            items=[_paper()],
            total=2,
        )

    def stats(
        self,
        *,
        actor: Actor,
    ) -> PaperSearchStats:
        raise AssertionError("stats is not used by this test")

    def search_candidates(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchCandidatePage:
        self.requests.append(request)
        paper = _paper()
        return PaperSearchCandidatePage(
            items=[
                PaperSearchCandidate(
                    document_id=paper.document_id,
                    title=paper.title,
                    abstract=paper.abstract,
                    created_at=paper.created_at,
                    last_accessed_at=paper.last_accessed_at,
                    snippets=paper.snippets,
                )
            ],
            total=2,
        )


class _SearchAccess:
    def require_collection_access(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
    ) -> None:
        pass


def test_search_cursor_round_trip_uses_backend_neutral_offset() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        _SearchAccess(),
    )

    first_page = search(
        actor=_actor(),
        request=PaperSearchRequest(query="  graph retrieval  ", limit=1),
    )
    assert first_page.next_cursor is not None
    assert backend.requests[0].query == "graph retrieval"
    assert backend.requests[0].offset == 0

    second_page = search(
        actor=_actor(),
        request=PaperSearchRequest(
            query="graph retrieval",
            limit=1,
            cursor=first_page.next_cursor,
        ),
    )
    assert backend.requests[1].offset == 1
    assert second_page.next_cursor is None


def test_composite_candidate_page_uses_one_bounded_rank_window() -> None:
    backend = _SearchBackend()
    access = _SearchAccess()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        access,
    )

    response = search.candidate_page(
        actor=_actor(),
        request=PaperSearchRequest(query="  graph retrieval  ", limit=25),
        offset=50,
    )

    assert len(response.items) == 1
    assert response.total == 2
    assert backend.requests == [
        PaperSearchQuery(
            query="graph retrieval",
            collection=LibraryPaperCollection(),
            filters=PaperSearchFilters(),
            sort=PaperSearchSort.RELEVANCE,
            limit=25,
            offset=50,
        )
    ]


def test_composite_candidate_projection_never_hydrates_full_document_fields() -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    document_id = uuid4()
    hostile = '\x00"\\😀' * 10_000
    projection = Mock()
    projection.mappings.return_value.all.return_value = [
        {
            "document_id": document_id,
            "title": hostile,
            "abstract": hostile,
            "summary": hostile,
            "created_at": now,
            "last_accessed_at": now,
            "raw_content": object(),
            "authors": object(),
            "keywords": object(),
        }
    ]
    passage = Mock()
    passage.all.return_value = [(document_id, 1, 2, hostile)]
    db = Mock(spec=Session)
    db.execute.side_effect = [projection, passage]
    search = PostgresPaperSearch(db, semantic=False)
    ranking = _SearchRanking(
        conditions=[],
        text_query="bounded-query",
        retrieval_modes={},
        semantic_ids=[],
        ranked_ids=[document_id],
    )

    with (
        patch.object(search, "_ranking", return_value=ranking),
        patch(
            "app.bootstrap.adapters.paper_search._fallback_snippet",
            side_effect=AssertionError("full Document fallback must not run"),
        ),
        patch(
            "app.bootstrap.adapters.paper_search._matching_fields",
            side_effect=AssertionError("full Document matching must not run"),
        ),
    ):
        page = search.search_candidates(
            actor=_actor(),
            request=PaperSearchQuery(
                query="graph retrieval",
                collection=LibraryPaperCollection(),
                filters=PaperSearchFilters(),
                sort=PaperSearchSort.RELEVANCE,
                limit=25,
                offset=0,
            ),
        )

    assert len(page.items) == 1
    item = page.items[0]
    assert len((item.title or "").encode("utf-8")) <= 384
    assert len((item.abstract or "").encode("utf-8")) <= 900
    assert len(item.snippets[0].text.encode("utf-8")) <= 900
    assert len(page.model_dump_json().encode("utf-8")) < 8_192

    projection_sql = " ".join(
        str(
            db.execute.call_args_list[0]
            .args[0]
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    ).lower()
    passage_sql = " ".join(
        str(
            db.execute.call_args_list[1]
            .args[0]
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    ).lower()
    assert "documents.raw_content" not in projection_sql
    assert "documents.authors" not in projection_sql
    assert "documents.keywords" not in projection_sql
    assert "left(scholens.documents.title" in projection_sql
    assert "left(scholens.documents.abstract" in projection_sql
    assert "left(scholens.documents.summary" in projection_sql
    assert "left(scholens.document_passages.content" in passage_sql


@pytest.mark.parametrize(
    ("cursor_mutation", "query"),
    [
        (
            lambda cursor: ("A" if cursor[0] != "A" else "B") + cursor[1:],
            "graph retrieval",
        ),
        (lambda cursor: cursor, "different query"),
    ],
)
def test_search_cursor_rejects_tampering_and_query_reuse(
    cursor_mutation: Callable[[str], str],
    query: str,
) -> None:
    codec = SearchCursorCodec("x" * 32)
    cursor = codec.encode(fingerprint="graph retrieval", offset=10)

    with pytest.raises(AppError) as error:
        codec.decode(
            cursor=cursor_mutation(cursor),
            fingerprint=query,
        )

    assert error.value.code == "search_cursor_expired"
    assert error.value.kind is FailureKind.CONFLICT


def test_search_cursor_is_bound_to_the_selected_collection() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        _SearchAccess(),
    )
    first_document = uuid4()
    first_page = search(
        actor=_actor(),
        request=PaperSearchRequest(
            query="graph retrieval",
            limit=1,
            collection=SelectedPaperCollection(document_ids=[first_document]),
        ),
    )

    assert first_page.next_cursor is not None
    with pytest.raises(AppError) as error:
        search(
            actor=_actor(),
            request=PaperSearchRequest(
                query="graph retrieval",
                limit=1,
                cursor=first_page.next_cursor,
                collection=SelectedPaperCollection(document_ids=[uuid4()]),
            ),
        )

    assert error.value.code == "search_cursor_expired"


def test_search_cursor_is_bound_to_personal_metadata_filters() -> None:
    backend = _SearchBackend()
    search = SearchPapers(
        backend,
        SearchCursorCodec("x" * 32),
        _SearchAccess(),
    )
    first_page = search(
        actor=_actor(),
        request=PaperSearchRequest(
            query="graph retrieval",
            limit=1,
            filters=PaperSearchFilters(
                personal_statuses=[PaperStatus.reading],
                personal_tag_ids=[uuid4()],
            ),
        ),
    )

    assert first_page.next_cursor is not None
    with pytest.raises(AppError) as error:
        search(
            actor=_actor(),
            request=PaperSearchRequest(
                query="graph retrieval",
                limit=1,
                cursor=first_page.next_cursor,
                filters=PaperSearchFilters(
                    personal_statuses=[PaperStatus.completed],
                ),
            ),
        )

    assert error.value.code == "search_cursor_expired"


def test_library_visibility_includes_personal_and_project_access() -> None:
    statement = str(
        _visibility_condition(
            actor=_actor(),
            collection=LibraryPaperCollection(),
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "library_papers" in statement
    assert "project_papers" in statement
    assert "projects" in statement
    assert "project_collaborators" in statement
    assert "owner_id" in statement


def test_compact_query_matches_joined_words_and_unicode_width() -> None:
    assert _compact_query("Code World-Model") == "codeworldmodel"
    assert _compact_query("Ｃｏｄｅ　World Model") == "codeworldmodel"


def test_personal_library_visibility_excludes_project_membership() -> None:
    statement = str(
        _visibility_condition(
            actor=_actor(),
            collection=PersonalLibraryPaperCollection(),
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "library_papers" in statement
    assert "user_id = 7" in statement
    assert "project_papers" not in statement
    assert "project_collaborators" not in statement


def test_library_search_compiles_with_distinct_result_and_visibility_rows() -> None:
    db = Mock(spec=Session)
    compiled_sql: list[str] = []

    def compile_statement(statement: ClauseElement) -> str:
        return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())

    def scalar(statement: ClauseElement) -> int:
        compiled_sql.append(compile_statement(statement))
        return 0

    rows = Mock()
    rows.all.return_value = []
    rows.tuples.return_value = []

    def execute(statement: ClauseElement) -> Mock:
        compiled_sql.append(compile_statement(statement))
        return rows

    db.scalar.side_effect = scalar
    db.execute.side_effect = execute
    db.scalars.side_effect = execute

    response = PostgresPaperSearch(db).search(
        actor=_actor(),
        request=PaperSearchQuery(
            query="graph retrieval",
            collection=LibraryPaperCollection(),
            filters=PaperSearchFilters(),
            sort=PaperSearchSort.RELEVANCE,
            limit=50,
            offset=0,
        ),
    )

    assert response.items == []
    assert response.total == 0
    assert len(compiled_sql) == 5
    assert any(
        "LEFT OUTER JOIN scholens.library_papers AS actor_library_entry" in statement
        for statement in compiled_sql
    )
    for statement in [compiled_sql[0], compiled_sql[1], *compiled_sql[3:]]:
        assert (
            "EXISTS (SELECT scholens.library_papers.id "
            "FROM scholens.library_papers "
            "WHERE scholens.library_papers.document_id = scholens.documents.id"
            in statement
        )
