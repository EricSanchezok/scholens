from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.papers.application import content as content_module
from app.modules.papers.application.content import (
    AccessiblePaperContent,
    AccessiblePaperContentPreview,
    PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES,
    PaperContentCapabilities,
    PaperContentRevision,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError
from app.modules.papers.infrastructure.content_gateway import (
    SqlAlchemyPaperContentGateway,
)
from app.tooling import serialize_tool_success
from app.tooling import workspace_handlers as workspace_handlers_module
from app.tooling.contracts import ToolExecutionContext
from app.tooling.paper_content_paging import PaperContentSnapshotCache
from app.tooling.workspace_contracts import (
    PaperContentSearchOutput,
    SearchPaperContentInput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


class _ContentPort:
    def __init__(self, *, document_id: UUID, raw_content: str) -> None:
        revision = hashlib.sha256(raw_content.encode()).hexdigest()
        self._paper = AccessiblePaperContent(
            document_id=document_id,
            original_filename="paper.pdf",
            title="Searchable paper",
            abstract=None,
            raw_content=raw_content,
            storage_key="private/source.pdf",
            parser_markdown_storage_key="private/canonical.md",
            content_revision=revision,
        )
        self.get_calls = 0
        self.revision_calls = 0
        self.retained_size_calls = 0

    def get_revision(
        self, *, actor: Actor, document_id: UUID
    ) -> PaperContentRevision | None:
        del actor
        self.revision_calls += 1
        if document_id != self._paper.document_id:
            return None
        return PaperContentRevision(
            document_id=document_id,
            revision=self._paper.content_revision,
        )

    def get_retained_size(
        self, *, actor: Actor, document_id: UUID
    ) -> PaperContentRevision | None:
        del actor
        self.retained_size_calls += 1
        if document_id != self._paper.document_id:
            return None
        return PaperContentRevision(
            document_id=document_id,
            revision=self._paper.content_revision,
        )

    def get(self, *, actor: Actor, document_id: UUID) -> AccessiblePaperContent | None:
        del actor
        self.get_calls += 1
        return self._paper if document_id == self._paper.document_id else None

    def get_snapshot(
        self, *, actor: Actor, document_id: UUID
    ) -> AccessiblePaperContent | None:
        return self.get(actor=actor, document_id=document_id)

    def get_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        max_characters: int,
    ) -> AccessiblePaperContentPreview | None:
        del actor
        if document_id != self._paper.document_id:
            return None
        content = self._paper.raw_content
        prefix = content[:max_characters] if content is not None else None
        return AccessiblePaperContentPreview(
            document_id=document_id,
            revision=self._paper.content_revision,
            content=prefix,
            total_lines=len(content.splitlines()) if content else 0,
            truncated=(content is not None and prefix != content),
        )


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _context(user_id: int = 7) -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=_actor(user_id),
        operation=operation,
        paper_collection=MagicMock(),
        anchor_document_id=None,
        invocation_id="paper-search-test",
        client_ip="test",
    )


def _handler(
    cache: PaperContentSnapshotCache | None = None,
) -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="paper-search-test-secret",
        paper_content_snapshot_cache=cache,
    )


def _capabilities(*, document_id: UUID, raw_content: str) -> SimpleNamespace:
    port = _ContentPort(document_id=document_id, raw_content=raw_content)
    paper_content = PaperContentCapabilities(
        port,
        lambda **_arguments: {document_id},
    )
    return SimpleNamespace(
        paper_collection_access=MagicMock(),
        paper_content=paper_content,
        paper_content_port=port,
    )


def test_paper_search_pages_all_matches_with_bounded_real_mcp_results() -> None:
    document_id = uuid4()
    raw_content = "\n".join(
        f"line {index} evidence {'界' * 2_000}" for index in range(25)
    )
    capabilities = _capabilities(document_id=document_id, raw_content=raw_content)
    handler = _handler()
    context = _context()
    request = SearchPaperContentInput(
        document_id=document_id,
        query="evidence",
        limit=7,
    )
    matches: list[str] = []
    final_total: int | None = None

    while True:
        outcome = handler.search_paper_content(capabilities, context, request)
        page = PaperContentSearchOutput.model_validate(outcome.payload)
        matches.extend(page.matches)
        assert len(page.matches) <= request.limit
        assert all(
            len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            <= PAPER_CONTENT_SEARCH_MATCH_JSON_BYTES
            for item in page.matches
        )
        assert serialize_tool_success(outcome).call_tool_result_utf8_bytes < 200_000
        if page.next_cursor is None:
            final_total = page.total_match_count
            break
        assert page.total_match_count is None
        request = request.model_copy(update={"cursor": page.next_cursor, "limit": 3})

    assert [int(item.partition(":")[0]) for item in matches] == list(range(1, 26))
    assert all(item.endswith("…") for item in matches)
    assert final_total == 25
    assert capabilities.paper_content_port.get_calls == 1
    assert capabilities.paper_content_port.revision_calls > 1
    assert (
        capabilities.paper_collection_access.call_count
        == capabilities.paper_content_port.revision_calls
    )


def test_paper_search_cursor_rejects_tamper_scope_and_stale_content() -> None:
    document_id = uuid4()
    original = _capabilities(
        document_id=document_id,
        raw_content="evidence\nevidence\nevidence",
    )
    handler = _handler()
    first = PaperContentSearchOutput.model_validate(
        handler.search_paper_content(
            original,
            _context(),
            SearchPaperContentInput(
                document_id=document_id,
                query="evidence",
                limit=1,
            ),
        ).payload
    )
    assert first.next_cursor is not None
    tampered_cursor = first.next_cursor[:-1] + (
        "A" if first.next_cursor[-1] != "A" else "B"
    )

    for context, capabilities, query, cursor in (
        (_context(8), original, "evidence", first.next_cursor),
        (_context(), original, "different", first.next_cursor),
        (
            _context(),
            _capabilities(document_id=document_id, raw_content="changed evidence"),
            "evidence",
            first.next_cursor,
        ),
        (_context(), original, "evidence", tampered_cursor),
    ):
        with pytest.raises(AppError) as excinfo:
            handler.search_paper_content(
                capabilities,
                context,
                SearchPaperContentInput(
                    document_id=document_id,
                    query=query,
                    cursor=cursor,
                ),
            )
        assert excinfo.value.code == "paper_content_search_cursor_invalid"


def test_paper_search_rejects_invalid_and_pathological_regex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    capabilities = _capabilities(
        document_id=document_id,
        raw_content=("a" * 100_000) + "!",
    )
    handler = _handler()

    with pytest.raises(AppError) as invalid:
        handler.search_paper_content(
            capabilities,
            _context(),
            SearchPaperContentInput(document_id=document_id, query="["),
        )
    assert invalid.value.code == "paper_content_search_pattern_invalid"

    monkeypatch.setattr(content_module, "PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(AppError) as timed_out:
        handler.search_paper_content(
            capabilities,
            _context(),
            SearchPaperContentInput(document_id=document_id, query="(a+)+$"),
        )
    assert timed_out.value.code == "paper_content_search_too_complex"


def test_paper_search_time_slice_returns_a_continuation_for_linear_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    content = "evidence\nsecond line\nthird line"
    capability = _capabilities(
        document_id=document_id,
        raw_content=content,
    ).paper_content
    clock = iter((0.0, 0.1, 0.6))
    monkeypatch.setattr(content_module, "monotonic", lambda: next(clock))

    page = capability.search_content(
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        query="evidence",
        limit=10,
    )

    assert page.matches == ("1: evidence",)
    assert page.next_offset == len("evidence\n")
    assert page.next_line == 2


def test_paper_search_immediate_expiry_never_returns_zero_progress_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    content = "evidence\nsecond line"
    capability = _capabilities(
        document_id=document_id,
        raw_content=content,
    ).paper_content
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(content_module, "monotonic", lambda: next(clock))

    with pytest.raises(AppError) as expired:
        capability.search_content(
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            query="evidence",
            limit=10,
        )

    assert expired.value.code == "paper_content_search_too_complex"


def test_paper_search_never_copies_an_unbounded_single_line() -> None:
    class SliceGuardString(str):
        def __getitem__(self, key: int | slice) -> str:
            if isinstance(key, slice):
                start, stop, _step = key.indices(len(self))
                assert (
                    stop - start
                    <= content_module.PAPER_CONTENT_SEARCH_MATCH_SOURCE_CHARACTERS
                )
            return super().__getitem__(key)

    content = SliceGuardString(("x" * (8 * 1024 * 1024)) + "evidence")
    capability = _capabilities(
        document_id=uuid4(),
        raw_content="unused",
    ).paper_content

    page = capability.search_content(
        content=content,
        content_sha256="stable-revision",
        query="evidence",
    )

    assert len(page.matches) == 1
    assert page.matches[0].startswith("1: ")
    assert page.matches[0].endswith("…")


def test_paper_search_rejects_excess_cache_hit_scan_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    cache = PaperContentSnapshotCache(max_concurrent_searches=1)
    handler = _handler(cache)
    capabilities = _capabilities(
        document_id=document_id,
        raw_content="bounded evidence",
    )
    monkeypatch.setattr(
        workspace_handlers_module,
        "PAPER_CONTENT_SEARCH_TIMEOUT_SECONDS",
        0,
    )

    with cache.search_slot(timeout_seconds=0):
        with pytest.raises(AppError) as rejected:
            handler.search_paper_content(
                capabilities,
                _context(),
                SearchPaperContentInput(
                    document_id=document_id,
                    query="evidence",
                ),
            )

    assert rejected.value.code == "paper_content_search_capacity_exceeded"
    assert rejected.value.kind.value == "rate_limited"


def test_content_revision_lookup_authorizes_without_selecting_raw_content() -> None:
    document_id = uuid4()
    updated_at = datetime.now(UTC)
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        id=document_id,
        updated_at=updated_at,
    )

    revision = SqlAlchemyPaperContentGateway(session).get_revision(
        actor=_actor(),
        document_id=document_id,
    )

    assert revision == PaperContentRevision(
        document_id=document_id,
        revision=updated_at.isoformat(),
    )
    statement = session.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "updated_at",
    )
    assert all(column.key != "raw_content" for column in statement.selected_columns)


def test_content_retained_size_lookup_uses_database_scalar_lengths() -> None:
    document_id = uuid4()
    updated_at = datetime.now(UTC)
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        id=document_id,
        updated_at=updated_at,
        raw_character_count=100,
        title_character_count=5,
    )

    revision = SqlAlchemyPaperContentGateway(session).get_retained_size(
        actor=_actor(),
        document_id=document_id,
    )

    assert revision == PaperContentRevision(
        document_id=document_id,
        revision=updated_at.isoformat(),
        retained_size_upper_bound=4_644,
    )
    statement = session.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "updated_at",
        "raw_character_count",
        "title_character_count",
    )
    assert all(column.key != "raw_content" for column in statement.selected_columns)


def test_content_preview_lookup_selects_only_a_bounded_prefix_and_scalar_facts() -> (
    None
):
    document_id = uuid4()
    updated_at = datetime.now(UTC)
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        id=document_id,
        updated_at=updated_at,
        content_prefix="first\nsecond",
        raw_character_count=10_000_000,
        total_lines=500_000,
    )

    preview = SqlAlchemyPaperContentGateway(session).get_preview(
        actor=_actor(),
        document_id=document_id,
        max_characters=16 * 1024,
    )

    assert preview == AccessiblePaperContentPreview(
        document_id=document_id,
        revision=updated_at.isoformat(),
        content="first\nsecond",
        total_lines=500_000,
        truncated=True,
    )
    statement = session.execute.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == (
        "id",
        "updated_at",
        "content_prefix",
        "raw_character_count",
        "total_lines",
    )
    assert all(column.key != "raw_content" for column in statement.selected_columns)
