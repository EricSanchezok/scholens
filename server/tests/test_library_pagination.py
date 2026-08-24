from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.papers.application.contracts.documents import (
    LibraryOutputSort,
    LibraryPaperListPaperEntry,
    LibraryPaperSort,
)
from app.modules.papers.application.library import (
    LibraryOutputPage,
    LibraryPageDirection,
    LibraryPagePosition,
    LibraryPaperPage,
    LibraryPaperSummaryPage,
    PaperLibrary,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _library(*, gateway: MagicMock, outputs: MagicMock) -> PaperLibrary:
    return PaperLibrary(
        gateway=gateway,
        outputs=outputs,
        capacity=MagicMock(),
        signer=MagicMock(),
        cursors=SignedCursorCodec(
            "library-test-secret",
            revision="library-v1",
            error_code="library_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=MagicMock(),
    )


def _paper_page(*, item_id: UUID, has_more: bool) -> LibraryPaperPage:
    return LibraryPaperPage(
        items=[LibraryPaperListPaperEntry.model_construct()],
        positions=[LibraryPagePosition(key="2026-08-11T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def _paper_summary_page(*, item_id: UUID, has_more: bool) -> LibraryPaperSummaryPage:
    return LibraryPaperSummaryPage(
        items=[LibraryPaperListPaperEntry.model_construct()],
        positions=[LibraryPagePosition(key="2026-08-11T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
        content_truncated=True,
    )


def test_durable_summary_cursor_is_bidirectional_and_uses_bounded_gateway() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    outputs = MagicMock()
    gateway.list.side_effect = AssertionError("full Library path must not run")
    gateway.list_summaries.side_effect = [
        _paper_summary_page(item_id=first_id, has_more=True),
        _paper_summary_page(item_id=second_id, has_more=False),
        _paper_summary_page(item_id=first_id, has_more=False),
    ]
    library = _library(gateway=gateway, outputs=outputs)

    first = library.list_summaries(actor=_actor(), query="graph", limit=1)
    assert first.value.next_cursor is not None
    assert first.content_truncated is True
    second = library.list_summaries(
        actor=_actor(),
        query="graph",
        cursor=first.value.next_cursor,
        limit=2,
    )
    assert second.value.previous_cursor is not None
    assert gateway.list_summaries.call_args_list[1].kwargs["position"].id == first_id
    assert gateway.list_summaries.call_args_list[1].kwargs["direction"] is (
        LibraryPageDirection.FORWARD
    )
    library.list_summaries(
        actor=_actor(),
        query="graph",
        cursor=second.value.previous_cursor,
        limit=1,
    )
    assert gateway.list_summaries.call_args_list[2].kwargs["direction"] is (
        LibraryPageDirection.BACKWARD
    )
    gateway.list.assert_not_called()


def test_paper_cursor_is_query_bound_and_supports_previous_navigation() -> None:
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    outputs = MagicMock()
    gateway.list.side_effect = [
        _paper_page(item_id=first_id, has_more=True),
        _paper_page(item_id=second_id, has_more=False),
        _paper_page(item_id=first_id, has_more=False),
    ]
    library = _library(gateway=gateway, outputs=outputs)

    first = library.list(actor=_actor(), query="graph", limit=1)
    assert first.next_cursor is not None
    assert first.previous_cursor is None

    second = library.list(
        actor=_actor(), query="graph", limit=1, cursor=first.next_cursor
    )
    assert second.previous_cursor is not None
    assert second.next_cursor is None
    assert gateway.list.call_args_list[1].kwargs["direction"] is (
        LibraryPageDirection.FORWARD
    )
    assert gateway.list.call_args_list[1].kwargs["position"].id == first_id

    previous = library.list(
        actor=_actor(), query="graph", limit=1, cursor=second.previous_cursor
    )
    assert previous.next_cursor is not None
    assert gateway.list.call_args_list[2].kwargs["direction"] is (
        LibraryPageDirection.BACKWARD
    )


@pytest.mark.parametrize(
    ("changed_argument", "value"),
    [
        ("query", "different"),
        ("sort", LibraryPaperSort.TITLE_ASC),
        ("actor", _actor(8)),
    ],
)
def test_paper_cursor_rejects_cross_query_reuse(
    changed_argument: str,
    value: object,
) -> None:
    gateway = MagicMock()
    outputs = MagicMock()
    gateway.list.return_value = _paper_page(item_id=uuid4(), has_more=True)
    library = _library(gateway=gateway, outputs=outputs)
    first = library.list(actor=_actor(), query="graph", limit=1)
    arguments: dict[str, object] = {
        "actor": _actor(),
        "query": "graph",
        "sort": LibraryPaperSort.ADDED_DESC,
        "limit": 1,
        "cursor": first.next_cursor,
    }
    arguments[changed_argument] = value

    with pytest.raises(AppError, match="cursor") as raised:
        library.list(**arguments)  # type: ignore[arg-type]

    assert raised.value.code == "library_cursor_invalid"


def test_paper_cursor_survives_page_size_changes() -> None:
    """Page size is a preference, not a filter: the same keyset cursor must
    remain valid when the caller changes limit between pages."""
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    outputs = MagicMock()
    gateway.list.side_effect = [
        _paper_page(item_id=first_id, has_more=True),
        _paper_page(item_id=second_id, has_more=False),
    ]
    library = _library(gateway=gateway, outputs=outputs)

    first = library.list(actor=_actor(), query="graph", limit=1)
    resized = library.list(
        actor=_actor(),
        query="graph",
        limit=50,
        cursor=first.next_cursor,
    )

    assert resized.total_count == 2
    assert gateway.list.call_args_list[1].kwargs["position"].id == first_id
    assert gateway.list.call_args_list[1].kwargs["limit"] == 50


def test_durable_paper_cursor_rejects_legacy_collection_scope_reuse() -> None:
    gateway = MagicMock()
    outputs = MagicMock()
    gateway.list.return_value = _paper_page(item_id=uuid4(), has_more=True)
    library = _library(gateway=gateway, outputs=outputs)

    durable = library.list(
        actor=_actor(),
        limit=5,
        include_active_ingestions=False,
    )
    assert durable.next_cursor is not None

    with pytest.raises(AppError, match="cursor") as raised:
        library.list(
            actor=_actor(),
            limit=5,
            cursor=durable.next_cursor,
            include_active_ingestions=True,
        )

    assert raised.value.code == "library_cursor_invalid"


def test_outputs_use_the_same_canonical_cursor_envelope() -> None:
    gateway = MagicMock()
    outputs = MagicMock()
    outputs.list.return_value = LibraryOutputPage(
        items=[],
        positions=[],
        has_more=False,
        total_count=4,
    )
    library = _library(gateway=gateway, outputs=outputs)

    response = library.list_outputs(
        actor=_actor(),
        query="citation",
        sort=LibraryOutputSort.TITLE_DESC,
    )

    assert response.total_count == 4
    assert response.items == []
    outputs.list.assert_called_once()


def _output_page(*, item_id: UUID, has_more: bool) -> LibraryOutputPage:
    return LibraryOutputPage(
        items=[],
        positions=[LibraryPagePosition(key="2026-08-11T10:00:00+00:00", id=item_id)],
        has_more=has_more,
        total_count=2,
    )


def test_outputs_cursor_survives_page_size_changes() -> None:
    """Page size is a preference, not a filter: the same keyset cursor must
    remain valid when the caller changes limit between output pages."""
    first_id = uuid4()
    second_id = uuid4()
    gateway = MagicMock()
    outputs = MagicMock()
    outputs.list.side_effect = [
        _output_page(item_id=first_id, has_more=True),
        _output_page(item_id=second_id, has_more=False),
    ]
    library = _library(gateway=gateway, outputs=outputs)

    first = library.list_outputs(actor=_actor(), query="citation", limit=1)
    resized = library.list_outputs(
        actor=_actor(),
        query="citation",
        limit=50,
        cursor=first.next_cursor,
    )

    assert resized.total_count == 2
    assert outputs.list.call_args_list[1].kwargs["position"].id == first_id
    assert outputs.list.call_args_list[1].kwargs["limit"] == 50


def test_outputs_accept_merge_base_three_value_cursor() -> None:
    previous_id = uuid4()
    gateway = MagicMock()
    outputs = MagicMock()
    outputs.list.return_value = _output_page(item_id=uuid4(), has_more=False)
    codec = SignedCursorCodec(
        "library-test-secret",
        revision="library-v1",
        error_code="library_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    filters = {
        "q": "citation",
        "kinds": [],
        "sort": LibraryOutputSort.UPDATED_DESC.value,
    }
    fingerprint = json.dumps(
        {
            "revision": "library-v1",
            "user_id": _actor().id,
            "collection": "outputs",
            "filters": filters,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    merge_base_cursor = codec.encode_keyset(
        fingerprint=fingerprint,
        values=("forward", "2026-08-11T10:00:00+00:00", str(previous_id)),
    )

    _library(gateway=gateway, outputs=outputs).list_outputs(
        actor=_actor(),
        query="citation",
        cursor=merge_base_cursor,
        limit=50,
    )

    position = outputs.list.call_args.kwargs["position"]
    assert position.id == previous_id
    assert position.kind == "paper"
    assert outputs.list.call_args.kwargs["direction"] is LibraryPageDirection.FORWARD
