from datetime import UTC, datetime
from typing import Callable
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.bootstrap.adapters.paper_search import (
    PostgresPaperSearch,
    _accepted_semantic_candidates,
    _compact_query,
    _contains_complete_metadata_token,
    _matching_passages,
    _metadata_exact_condition,
    _query_plan,
    _visibility_condition,
)
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    PersonalLibraryPaperCollection,
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
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain.enums import PaperStatus
from app.shared.domain import AppError, FailureKind
from app.shared.infrastructure.text_excerpt import plain_query_excerpt
from sqlalchemy.dialects import postgresql
from sqlalchemy import func
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


def test_search_cursor_rejects_previous_ranking_revision() -> None:
    secret = "x" * 32
    legacy = SignedCursorCodec(
        secret,
        revision="paper-search:2",
        error_code="search_cursor_expired",
    )
    cursor = legacy.encode(fingerprint="graph retrieval", offset=10)

    with pytest.raises(AppError) as error:
        SearchCursorCodec(secret).decode(
            cursor=cursor,
            fingerprint="graph retrieval",
        )

    assert error.value.code == "search_cursor_expired"


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


def test_compact_query_normalizes_joined_and_compatibility_form_user_input() -> None:
    assert _compact_query("Code World-Model") == "codeworldmodel"
    assert _compact_query("Ｃｏｄｅ　World Model") == "codeworldmodel"


@pytest.mark.parametrize(
    ("query", "hybrid", "publication_year"),
    [
        ("23", False, None),
        ("2023", False, 2023),
        ("Li", False, None),
        ("R2", False, None),
        ("abc", True, None),
        ("AI agents", True, None),
        ("论文", True, None),
        ("论", False, None),
    ],
)
def test_query_plan_keeps_ambiguous_short_terms_out_of_hybrid_retrieval(
    query: str,
    hybrid: bool,
    publication_year: int | None,
) -> None:
    plan = _query_plan(query)

    assert plan.hybrid is hybrid
    assert plan.publication_year == publication_year


def test_four_digit_metadata_query_matches_publication_year_without_body_search() -> (
    None
):
    condition = _metadata_exact_condition(_query_plan("2023"))
    compiled = str(
        condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "EXTRACT(year FROM scholens.documents.publish_date) = 2023" in compiled
    assert "array_to_string(scholens.documents.authors" in compiled
    assert "array_to_string(scholens.documents.keywords" in compiled
    assert "search_text_compact" not in compiled
    assert " LIKE " not in compiled
    assert "raw_content" not in compiled
    assert "ts_vector" not in compiled


def test_short_metadata_query_uses_word_boundaries_and_normalized_doi_equality() -> (
    None
):
    condition = _metadata_exact_condition(_query_plan("Li"))
    compiled = str(
        condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    word_boundary = "~* '(^|[^[:alnum:]])li([^[:alnum:]]|$)'"
    assert compiled.count(word_boundary) == 3
    assert "array_to_string(scholens.documents.authors" in compiled
    assert "array_to_string(scholens.documents.keywords" in compiled
    assert "doi" in compiled and " = 'li'" in compiled
    assert " LIKE " not in compiled
    assert "search_text_compact" not in compiled
    assert _contains_complete_metadata_token("Jinghua Li", "li")
    assert _contains_complete_metadata_token("Li, Jinghua", "li")
    assert not _contains_complete_metadata_token("Alice Yang", "li")
    assert not _contains_complete_metadata_token("Liminal systems", "li")


def test_exact_metadata_prevents_semantic_expansion() -> None:
    exact_id = uuid4()
    lexical_id = uuid4()
    semantic_only_id = uuid4()

    accepted = _accepted_semantic_candidates(
        [(semantic_only_id, 0.05), (exact_id, 0.10), (lexical_id, 0.40)],
        lexical_ids={exact_id, lexical_id},
        has_exact_metadata=True,
    )

    assert accepted == [exact_id, lexical_id]


def test_semantic_only_candidates_require_absolute_and_relative_relevance() -> None:
    best_id = uuid4()
    relative_edge_id = uuid4()
    outside_relative_id = uuid4()
    outside_absolute_id = uuid4()
    lexical_id = uuid4()

    accepted = _accepted_semantic_candidates(
        [
            (best_id, 0.15),
            (relative_edge_id, 0.189),
            (outside_relative_id, 0.191),
            (outside_absolute_id, 0.201),
            (lexical_id, 0.90),
        ],
        lexical_ids={lexical_id},
        has_exact_metadata=False,
    )

    assert accepted == [best_id, relative_edge_id, lexical_id]


def test_semantic_only_acceptance_is_capped_and_can_return_no_results() -> None:
    within_window = [(uuid4(), 0.10) for _index in range(25)]

    assert (
        len(
            _accepted_semantic_candidates(
                within_window,
                lexical_ids=set(),
                has_exact_metadata=False,
            )
        )
        == 20
    )
    assert (
        _accepted_semantic_candidates(
            [(uuid4(), 0.21), (uuid4(), 0.25)],
            lexical_ids=set(),
            has_exact_metadata=False,
        )
        == []
    )


def test_search_total_and_mode_use_only_accepted_semantic_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted_id = uuid4()
    rejected_id = uuid4()
    db = Mock(spec=Session)

    candidate_rows = Mock()
    candidate_rows.tuples.return_value = []
    semantic_rows = Mock()
    semantic_rows.tuples.return_value = [
        (accepted_id, 0.10),
        (rejected_id, 0.30),
    ]
    detail_rows = Mock()
    detail_rows.all.return_value = []
    db.execute.side_effect = [candidate_rows, semantic_rows, detail_rows]
    lexical_rows = Mock()
    lexical_rows.all.return_value = []
    db.scalars.return_value = lexical_rows
    db.scalar.side_effect = [0, 0]

    class _Embedder:
        def embed_query(self, _query: str) -> list[float]:
            return [0.0] * 384

    monkeypatch.setattr(
        "app.bootstrap.adapters.paper_search.try_local_embedder",
        lambda: _Embedder(),
    )

    response = PostgresPaperSearch(db).search(
        actor=_actor(),
        request=PaperSearchQuery(
            query="approximate agent topic",
            collection=LibraryPaperCollection(),
            filters=PaperSearchFilters(),
            sort=PaperSearchSort.RELEVANCE,
            limit=50,
            offset=100,
        ),
    )

    assert response.items == []
    assert response.total == 1
    assert response.search_mode == "hybrid"


def test_plain_excerpt_centers_literal_match_and_bounds_markup() -> None:
    dirty = (
        "# Header\n"
        "[unrelated link](https://example.com) "
        + ("prefix " * 80)
        + "target phrase **with emphasis** "
        + ("suffix " * 80)
    )

    excerpt = plain_query_excerpt(
        dirty,
        "target phrase",
        limit=240,
    )

    assert excerpt is not None
    assert "target phrase" in excerpt
    assert "https://" not in excerpt
    assert "**" not in excerpt
    assert "\n" not in excerpt
    assert len(excerpt) <= 240


def test_matching_passages_preserve_locators_and_use_ranked_headlines() -> None:
    document_id = uuid4()
    db = Mock(spec=Session)
    rows = Mock()
    rows.all.return_value = [
        (
            document_id,
            11,
            15,
            "…before <b>target phrase</b> **finding** after…",
        ),
    ]
    db.execute.return_value = rows

    snippets = _matching_passages(
        db,
        document_ids=[document_id],
        text_query=func.websearch_to_tsquery(
            "pg_catalog.english",
            "target phrase",
        ),
        query="target phrase",
    )

    assert len(snippets[document_id]) == 1
    assert snippets[document_id][0].start_line == 11
    assert snippets[document_id][0].end_line == 15
    assert "target phrase" in snippets[document_id][0].text
    assert "**" not in snippets[document_id][0].text
    assert len(snippets[document_id][0].text) <= 240
    statement = str(
        db.execute.call_args.args[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "ts_headline" in statement


def test_matching_passages_keep_stemmed_full_text_matches() -> None:
    document_id = uuid4()
    db = Mock(spec=Session)
    rows = Mock()
    rows.all.return_value = [
        (document_id, 21, 25, "…a stemmed <b>agent</b> match…"),
    ]
    db.execute.return_value = rows

    snippets = _matching_passages(
        db,
        document_ids=[document_id],
        text_query=func.websearch_to_tsquery("pg_catalog.english", "agents"),
        query="agents",
    )

    assert snippets[document_id][0].text == "…a stemmed agent match…"


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


def test_short_numeric_search_skips_fuzzy_full_text_and_semantic_candidate_lanes() -> (
    None
):
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
            query="23",
            collection=LibraryPaperCollection(),
            filters=PaperSearchFilters(),
            sort=PaperSearchSort.RELEVANCE,
            limit=50,
            offset=0,
        ),
    )

    assert response.items == []
    assert response.total == 0
    assert response.search_mode == "lexical"
    assert len(compiled_sql) == 4
    candidate_statement = compiled_sql[0]
    assert "similarity(" not in candidate_statement
    assert "search_text_compact" not in candidate_statement
    assert "ts_vector" not in candidate_statement
    assert not any("document_passages" in statement for statement in compiled_sql)
    assert not any("cosine_distance" in statement for statement in compiled_sql)
