from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.bootstrap.adapters.paper_collection_access import SqlPaperCollectionAccess
from app.modules.papers.application.content import (
    AccessiblePaperContent,
    PaperContentCapabilities,
    PaperContentRevision,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
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
from app.tooling import serialize_tool_success
from app.tooling.contracts import ToolExecutionContext
from app.tooling.paper_content_paging import PAPER_CONTENT_OUTPUT_BYTES
from app.tooling.workspace_contracts import (
    PaperContentInput,
    PaperContentOutput,
)
from app.tooling.workspace_handlers import WorkspaceToolHandlers


def _context(user_id: int = 7) -> ToolExecutionContext:
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=Actor(
            id=user_id,
            email=f"reader-{user_id}@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation,
        paper_collection=MagicMock(),
        anchor_document_id=None,
        invocation_id="paper-content-test",
        client_ip="test",
    )


def _handler() -> WorkspaceToolHandlers:
    return WorkspaceToolHandlers(
        executor=MagicMock(),
        ingestion=MagicMock(),
        citations=MagicMock(),
        web_base_url="https://scholens.example",
        cursor_secret="paper-content-test-secret",
    )


class _ContentPort:
    def __init__(self, paper: AccessiblePaperContent) -> None:
        self.paper = paper
        self.authorized = True
        self.get_calls = 0
        self.revision_calls = 0
        self.retained_size_calls = 0
        self.retained_size_upper_bound: int | None = None

    def get_revision(self, *, actor: Actor, document_id) -> PaperContentRevision | None:
        del actor
        self.revision_calls += 1
        if not self.authorized or document_id != self.paper.document_id:
            return None
        return PaperContentRevision(
            document_id=document_id,
            revision=self.paper.content_revision,
        )

    def get_retained_size(
        self, *, actor: Actor, document_id
    ) -> PaperContentRevision | None:
        del actor
        self.retained_size_calls += 1
        if not self.authorized or document_id != self.paper.document_id:
            return None
        return PaperContentRevision(
            document_id=document_id,
            revision=self.paper.content_revision,
            retained_size_upper_bound=self.retained_size_upper_bound,
        )

    def get(self, *, actor: Actor, document_id) -> AccessiblePaperContent | None:
        del actor
        self.get_calls += 1
        if not self.authorized or document_id != self.paper.document_id:
            return None
        return self.paper

    def get_snapshot(
        self, *, actor: Actor, document_id
    ) -> AccessiblePaperContent | None:
        return self.get(actor=actor, document_id=document_id)


def _capabilities(
    *,
    document_id,
    raw_content: str,
    title: str = "Unicode paper",
    revision: str | None = None,
) -> SimpleNamespace:
    content_revision = revision or hashlib.sha256(raw_content.encode()).hexdigest()
    paper = AccessiblePaperContent(
        document_id=document_id,
        original_filename="paper.pdf",
        title=title,
        abstract=None,
        raw_content=raw_content,
        storage_key="private/source.pdf",
        parser_markdown_storage_key="private/canonical.md",
        content_revision=content_revision,
    )
    port = _ContentPort(paper)
    return SimpleNamespace(
        paper_collection_access=MagicMock(),
        paper_content=PaperContentCapabilities(
            port,
            lambda **_arguments: {document_id},
        ),
        paper_content_port=port,
    )


def _encoded_outcome_bytes(outcome) -> int:
    return serialize_tool_success(outcome).call_tool_result_utf8_bytes


def test_paper_content_start_line_matches_the_effective_integer_range() -> None:
    document_id = uuid4()
    maximum = (1 << 63) - 1

    accepted = PaperContentInput(document_id=document_id, start_line=maximum)

    assert accepted.start_line == maximum
    assert (
        PaperContentInput.model_json_schema()["properties"]["start_line"]["maximum"]
        == maximum
    )
    with pytest.raises(ValidationError):
        PaperContentInput(document_id=document_id, start_line=maximum + 1)
    with pytest.raises(AppError) as after_end:
        _handler().get_paper_content(
            _capabilities(document_id=document_id, raw_content="one line"),
            _context(),
            accepted,
        )
    assert after_end.value.code == "paper_content_start_invalid"


def test_paper_content_cursor_reassembles_one_long_unicode_line_losslessly() -> None:
    document_id = uuid4()
    raw_content = "开头🙂" + ("界🔬" * 30_000) + "结尾"
    capabilities = _capabilities(document_id=document_id, raw_content=raw_content)
    handler = _handler()
    context = _context()
    request = PaperContentInput(
        document_id=document_id,
        max_lines=500,
        max_utf8_bytes=4_096,
    )
    fragments: list[str] = []

    while True:
        requested_bytes = request.max_utf8_bytes
        outcome = handler.get_paper_content(capabilities, context, request)
        page = PaperContentOutput.model_validate(outcome.payload)
        fragments.append(page.content)
        assert page.content_utf8_bytes <= requested_bytes
        assert _encoded_outcome_bytes(outcome) <= PAPER_CONTENT_OUTPUT_BYTES
        if page.next_cursor is None:
            break
        assert page.next_start_line is None
        request = request.model_copy(
            update={"cursor": page.next_cursor, "max_utf8_bytes": 8_192}
        )

    assert "".join(fragments) == raw_content
    assert "\ufffd" not in "".join(fragments)
    assert capabilities.paper_content_port.get_calls == 1
    assert capabilities.paper_content_port.revision_calls == len(fragments)
    assert capabilities.paper_collection_access.call_count == len(fragments)


def test_paper_content_cursor_is_bound_to_actor_document_and_content_revision() -> None:
    document_id = uuid4()
    handler = _handler()
    context = _context()
    first_capabilities = _capabilities(
        document_id=document_id,
        raw_content="evidence " * 10_000,
    )
    first = PaperContentOutput.model_validate(
        handler.get_paper_content(
            first_capabilities,
            context,
            PaperContentInput(document_id=document_id, max_utf8_bytes=4_096),
        ).payload
    )
    assert first.next_cursor is not None

    changed_capabilities = _capabilities(
        document_id=document_id,
        raw_content="changed evidence " * 10_000,
    )
    with pytest.raises(AppError) as stale:
        handler.get_paper_content(
            changed_capabilities,
            context,
            PaperContentInput(document_id=document_id, cursor=first.next_cursor),
        )
    assert stale.value.code == "paper_content_cursor_invalid"

    with pytest.raises(AppError) as tampered:
        tampered_cursor = first.next_cursor[:-1] + (
            "A" if first.next_cursor[-1] != "A" else "B"
        )
        handler.get_paper_content(
            first_capabilities,
            context,
            PaperContentInput(
                document_id=document_id,
                cursor=tampered_cursor,
            ),
        )
    assert tampered.value.code == "paper_content_cursor_invalid"


def test_paper_content_retains_legacy_line_continuation_at_a_boundary() -> None:
    document_id = uuid4()
    outcome = _handler().get_paper_content(
        _capabilities(document_id=document_id, raw_content="一\ntwo\nthree"),
        _context(),
        PaperContentInput(document_id=document_id, max_lines=2),
    )
    page = PaperContentOutput.model_validate(outcome.payload)

    assert page.content == "一\ntwo\n"
    assert page.lines == ["1: 一", "2: two"]
    assert page.next_start_line == 3
    assert page.next_cursor is not None
    assert page.starts_mid_line is False
    assert page.ends_mid_line is False


def test_paper_content_returns_project_scoped_reader_url() -> None:
    document_id = uuid4()
    project_id = uuid4()
    capabilities = _capabilities(document_id=document_id, raw_content="evidence")

    outcome = _handler().get_paper_content(
        capabilities,
        _context(),
        PaperContentInput(document_id=document_id, project_id=project_id),
    )
    page = PaperContentOutput.model_validate(outcome.payload)

    assert page.reader_url == (
        f"https://scholens.example/reader/{document_id}?project={project_id}"
    )
    authorized_collection = capabilities.paper_collection_access.call_args.kwargs[
        "collection"
    ]
    assert authorized_collection.project_ids == [project_id]


def test_paper_content_envelope_bounds_json_escape_heavy_source_excerpt() -> None:
    document_id = uuid4()
    outcome = _handler().get_paper_content(
        _capabilities(
            document_id=document_id,
            raw_content=('\\"\x00\n' * 20_000) + "tail",
        ),
        _context(),
        PaperContentInput(document_id=document_id),
    )

    page = PaperContentOutput.model_validate(outcome.payload)
    assert page.next_cursor is not None
    assert _encoded_outcome_bytes(outcome) <= PAPER_CONTENT_OUTPUT_BYTES


def test_paper_content_bounds_hostile_title_in_payload_source_and_link() -> None:
    document_id = uuid4()
    title = "\x00🧪" * 100_000
    outcome = _handler().get_paper_content(
        _capabilities(document_id=document_id, raw_content="short text", title=title),
        _context(),
        PaperContentInput(document_id=document_id),
    )

    page = PaperContentOutput.model_validate(outcome.payload)
    assert page.title_truncated is True
    assert page.title is not None
    assert len(page.title) < len(title)
    assert len(outcome.resource_links[0].name) < len(title)
    assert outcome.sources[0].title is not None
    assert len(outcome.sources[0].title) < len(title)
    assert _encoded_outcome_bytes(outcome) <= PAPER_CONTENT_OUTPUT_BYTES


def test_cached_content_revalidates_authorization_before_every_page() -> None:
    document_id = uuid4()
    capabilities = _capabilities(
        document_id=document_id,
        raw_content="evidence " * 10_000,
    )
    handler = _handler()
    first = PaperContentOutput.model_validate(
        handler.get_paper_content(
            capabilities,
            _context(),
            PaperContentInput(document_id=document_id, max_utf8_bytes=4_096),
        ).payload
    )
    assert first.next_cursor is not None
    capabilities.paper_content_port.authorized = False

    with pytest.raises(AppError) as revoked:
        handler.get_paper_content(
            capabilities,
            _context(),
            PaperContentInput(document_id=document_id, cursor=first.next_cursor),
        )

    assert revoked.value.code == "paper_not_found"
    assert capabilities.paper_content_port.revision_calls == 2
    assert capabilities.paper_content_port.get_calls == 1
    assert capabilities.paper_collection_access.call_count == 2


def test_paper_content_cache_is_actor_scoped_even_for_the_same_revision() -> None:
    document_id = uuid4()
    capabilities = _capabilities(
        document_id=document_id,
        raw_content="shared project evidence",
    )
    handler = _handler()

    for user_id in (7, 8):
        handler.get_paper_content(
            capabilities,
            _context(user_id),
            PaperContentInput(document_id=document_id),
        )

    assert capabilities.paper_content_port.revision_calls == 2
    assert capabilities.paper_content_port.get_calls == 2


def test_concurrent_same_revision_pages_hydrate_paper_content_once() -> None:
    document_id = uuid4()
    capabilities = _capabilities(
        document_id=document_id,
        raw_content="shared evidence " * 10_000,
    )
    handler = _handler()
    barrier = Barrier(8)

    def read_page() -> PaperContentOutput:
        barrier.wait(timeout=2)
        return PaperContentOutput.model_validate(
            handler.get_paper_content(
                capabilities,
                _context(),
                PaperContentInput(document_id=document_id),
            ).payload
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        pages = list(executor.map(lambda _index: read_page(), range(8)))

    assert all(page.content_sha256 == pages[0].content_sha256 for page in pages)
    assert capabilities.paper_content_port.get_calls == 1
    assert capabilities.paper_content_port.retained_size_calls == 1


def test_paper_content_size_preflight_rejects_before_full_hydration() -> None:
    document_id = uuid4()
    capabilities = _capabilities(
        document_id=document_id,
        raw_content="small fixture that must not be hydrated",
    )
    capabilities.paper_content_port.retained_size_upper_bound = 70 * 1024 * 1024

    with pytest.raises(AppError) as raised:
        _handler().get_paper_content(
            capabilities,
            _context(),
            PaperContentInput(document_id=document_id),
        )

    assert raised.value.code == "paper_content_paging_limit_exceeded"
    assert capabilities.paper_content_port.get_calls == 0
    assert capabilities.paper_content_port.retained_size_calls == 1


def test_paper_content_continuation_is_stale_after_revision_advances() -> None:
    document_id = uuid4()
    handler = _handler()
    original = _capabilities(
        document_id=document_id,
        raw_content="evidence " * 10_000,
        revision="revision-1",
    )
    first = PaperContentOutput.model_validate(
        handler.get_paper_content(
            original,
            _context(),
            PaperContentInput(document_id=document_id, max_utf8_bytes=4_096),
        ).payload
    )
    assert first.next_cursor is not None
    advanced = _capabilities(
        document_id=document_id,
        raw_content=original.paper_content_port.paper.raw_content or "",
        revision="revision-2",
    )

    with pytest.raises(AppError) as stale:
        handler.get_paper_content(
            advanced,
            _context(),
            PaperContentInput(document_id=document_id, cursor=first.next_cursor),
        )

    assert stale.value.code == "paper_content_cursor_invalid"
    assert advanced.paper_content_port.get_calls == 1


def test_collection_preflight_selects_only_document_identity() -> None:
    document_id = uuid4()
    session = MagicMock()
    session.scalar.return_value = document_id

    allowed = SqlPaperCollectionAccess(session).contains(
        actor=_context().actor,
        collection=LibraryPaperCollection(),
        document_id=document_id,
    )

    assert allowed is True
    statement = session.scalar.call_args.args[0]
    assert tuple(column.key for column in statement.selected_columns) == ("id",)
    assert "raw_content" not in str(statement)
