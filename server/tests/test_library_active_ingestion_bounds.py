from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.papers.application.contracts.documents import (
    LibraryPaperListPaperEntry,
)
from app.modules.papers.application.library import (
    LibraryPageDirection,
    LibraryPagePosition,
)
from app.modules.papers.application.contracts.documents import LibraryPaperSort
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
)
from app.modules.papers.infrastructure import library_gateway as library_gateway_module
from app.shared.domain.enums import JobStatus
from sqlalchemy.orm import Session


def test_active_reservations_use_count_and_strict_limit_scalar_projection() -> None:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [1_000, 0]
    now = datetime(2026, 8, 24, tzinfo=UTC)
    reservation_rows = [
        SimpleNamespace(
            job_id=uuid4(),
            display_name=f"queued-{index}.pdf",
            source_kind="upload",
            status=JobStatus.PENDING.value,
            progress_code=None,
            project_id=None,
            document_id=None,
            error_code=None,
            created_at=now,
        )
        for index in range(5)
    ]
    db.execute.return_value.all.return_value = reservation_rows
    db.scalars.return_value.all.return_value = []
    gateway = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    page = gateway.list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert len(page.items) == 5
    assert page.total_count == 1_000
    assert all(item.entry_type == "ingestion" for item in page.items)
    reservation_statement = db.execute.call_args.args[0]
    assert tuple(column.key for column in reservation_statement.selected_columns) == (
        "job_id",
        "display_name",
        "source_kind",
        "status",
        "progress_code",
        "project_id",
        "document_id",
        "error_code",
        "created_at",
    )
    assert reservation_statement._limit_clause.value == 6


def test_active_reservation_keyset_pages_have_no_duplicates_or_omissions() -> None:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [12, 0, 12, 0, 12, 0]
    now = datetime(2026, 8, 24, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            job_id=uuid4(),
            display_name=f"queued-{index}.pdf",
            source_kind="upload",
            status=JobStatus.PENDING.value,
            progress_code=None,
            project_id=None,
            document_id=None,
            error_code=None,
            created_at=now.replace(microsecond=12 - index),
        )
        for index in range(12)
    ]
    execute_results = []
    for page_rows in (rows[:6], rows[5:11], rows[10:]):
        result = MagicMock()
        result.all.return_value = page_rows
        execute_results.append(result)
    db.execute.side_effect = execute_results
    db.scalars.return_value.all.return_value = []
    gateway = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    position = None
    seen_ids = []
    for page_index in range(3):
        page = gateway.list(
            user_id=7,
            query=None,
            tag_ids=(),
            sort=LibraryPaperSort.ADDED_DESC,
            limit=5,
            direction=LibraryPageDirection.FORWARD,
            position=position,
        )
        assert len(page.items) <= 5
        assert page.total_count == 12
        assert page.has_more is (page_index < 2)
        seen_ids.extend(item.ingestion.id for item in page.items)
        position = page.positions[-1]
        assert position.kind == "ingestion"

    assert seen_ids == [row.job_id for row in rows]
    assert len(set(seen_ids)) == 12


def test_backward_paper_cursor_crosses_the_exact_limit_ingestion_seam() -> None:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [5, 1]
    now = datetime(2026, 8, 24, tzinfo=UTC)
    natural_rows = [
        SimpleNamespace(
            job_id=uuid4(),
            display_name=f"queued-{index}.pdf",
            source_kind="upload",
            status=JobStatus.PENDING.value,
            progress_code=None,
            project_id=None,
            document_id=None,
            error_code=None,
            created_at=now.replace(microsecond=5 - index),
        )
        for index in range(5)
    ]
    # A backward SQL page is read oldest-first and normalized back to the
    # collection's natural newest-first order by the gateway.
    db.execute.return_value.all.return_value = list(reversed(natural_rows))
    db.scalars.return_value.all.return_value = []
    gateway = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    page = gateway.list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.BACKWARD,
        position=LibraryPagePosition(
            key=now.isoformat(),
            id=uuid4(),
            kind="paper",
        ),
    )

    assert [item.ingestion.id for item in page.items] == [
        row.job_id for row in natural_rows
    ]
    assert [position.kind for position in page.positions] == ["ingestion"] * 5
    assert page.total_count == 6
    assert page.has_more is False


def test_exact_limit_ingestion_page_still_points_to_the_paper_segment() -> None:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [5, 1]
    now = datetime(2026, 8, 24, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            job_id=uuid4(),
            display_name=f"queued-{index}.pdf",
            source_kind="upload",
            status=JobStatus.PENDING.value,
            progress_code=None,
            project_id=None,
            document_id=None,
            error_code=None,
            created_at=now.replace(microsecond=5 - index),
        )
        for index in range(5)
    ]
    db.execute.return_value.all.return_value = rows
    db.scalars.return_value.all.return_value = []
    gateway = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    page = gateway.list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert len(page.items) == 5
    assert page.has_more is True
    assert page.total_count == 6


def test_mixed_ingestion_paper_page_roundtrips_across_the_segment_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    reservation_rows = [
        SimpleNamespace(
            job_id=uuid4(),
            display_name=f"queued-{index}.pdf",
            source_kind="upload",
            status=JobStatus.PENDING.value,
            progress_code=None,
            project_id=None,
            document_id=None,
            error_code=None,
            created_at=now.replace(microsecond=6 - index),
        )
        for index in range(3)
    ]
    paper_rows = [
        SimpleNamespace(
            id=uuid4(),
            document_id=uuid4(),
            created_at=now.replace(microsecond=3 - index),
        )
        for index in range(3)
    ]
    paper_responses = {
        row.id: LibraryPaperListPaperEntry.model_construct(
            entry_type="paper",
            library_entry_id=row.id,
        )
        for row in paper_rows
    }
    monkeypatch.setattr(
        library_gateway_module,
        "library_paper_list_response",
        lambda entry: paper_responses[entry.id],
    )

    forward_db = MagicMock(spec=Session)
    forward_db.scalar.side_effect = [3, 3]
    forward_db.execute.return_value.all.return_value = reservation_rows
    forward_papers = MagicMock()
    forward_papers.all.return_value = paper_rows[:2]
    forward_ids = MagicMock()
    forward_ids.all.return_value = [row.id for row in paper_rows]
    no_lifecycle = MagicMock()
    no_lifecycle.all.return_value = []
    forward_db.scalars.side_effect = [
        forward_ids,
        forward_papers,
        no_lifecycle,
    ]
    forward_gateway = SqlAlchemyPaperLibraryGateway(
        forward_db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    first = forward_gateway.list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.FORWARD,
        position=None,
    )

    assert [position.kind for position in first.positions] == [
        "ingestion",
        "ingestion",
        "ingestion",
        "paper",
        "paper",
    ]
    assert first.positions[-1].id == paper_rows[1].id
    assert first.has_more is True

    backward_db = MagicMock(spec=Session)
    backward_db.scalar.side_effect = [3, 3]
    backward_db.execute.return_value.all.return_value = list(reversed(reservation_rows))
    backward_papers = MagicMock()
    # Reverse SQL order yields the two papers nearest the third paper first.
    backward_papers.all.return_value = [paper_rows[1], paper_rows[0]]
    backward_ids = MagicMock()
    backward_ids.all.return_value = [paper_rows[1].id, paper_rows[0].id]
    backward_no_lifecycle = MagicMock()
    backward_no_lifecycle.all.return_value = []
    backward_db.scalars.side_effect = [
        backward_ids,
        backward_papers,
        backward_no_lifecycle,
    ]
    backward_gateway = SqlAlchemyPaperLibraryGateway(
        backward_db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    )

    reconstructed_first = backward_gateway.list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=5,
        direction=LibraryPageDirection.BACKWARD,
        position=LibraryPagePosition(
            key=paper_rows[2].created_at.isoformat(),
            id=paper_rows[2].id,
            kind="paper",
        ),
    )

    assert reconstructed_first.positions == first.positions
    assert reconstructed_first.total_count == first.total_count == 6
    assert reconstructed_first.has_more is False


def test_legacy_page_never_hydrates_the_limit_plus_one_probe_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    page_id = uuid4()
    poison_next_id = uuid4()
    page_entry = SimpleNamespace(
        id=page_id,
        document_id=uuid4(),
        created_at=now,
    )
    monkeypatch.setattr(
        library_gateway_module,
        "library_paper_list_response",
        lambda entry: LibraryPaperListPaperEntry.model_construct(
            entry_type="paper",
            library_entry_id=entry.id,
        ),
    )
    id_results = MagicMock()
    id_results.all.return_value = [page_id, poison_next_id]
    size_results = MagicMock()
    size_results.all.return_value = [4_096]
    hydrated_results = MagicMock()
    hydrated_results.all.return_value = [page_entry]
    db = MagicMock(spec=Session)
    db.scalar.return_value = 2
    db.scalars.side_effect = [id_results, size_results, hydrated_results]

    page = SqlAlchemyPaperLibraryGateway(
        db,
        document_removed=MagicMock(),
        personal_annotations_removed=MagicMock(),
    ).list(
        user_id=7,
        query=None,
        tag_ids=(),
        sort=LibraryPaperSort.ADDED_DESC,
        limit=1,
        direction=LibraryPageDirection.FORWARD,
        position=None,
        include_active_ingestions=False,
        maximum_retained_bytes=64 * 1024,
    )

    assert page.has_more is True
    assert [item.library_entry_id for item in page.items] == [page_id]
    id_statement, size_statement, hydrate_statement = (
        call.args[0] for call in db.scalars.call_args_list
    )
    assert id_statement._limit_clause is not None
    assert not id_statement._with_options
    for statement in (size_statement, hydrate_statement):
        params = statement.compile().params
        assert [page_id] in params.values()
        assert poison_next_id not in params.values()
    assert hydrate_statement._with_options
