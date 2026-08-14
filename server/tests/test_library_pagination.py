from __future__ import annotations

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
