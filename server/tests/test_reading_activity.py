"""High-value invariants for the first-party reading activity ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Table, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import load_only

from app.bootstrap.adapters.reading_activity_paper_queries import (
    PaperInsightsRepository,
)
from app.bootstrap.app_factory import create_app
from app.modules.reading_activity.application import (
    ReadingActivity,
    ReadingActivityRetention,
    ReadingActivityRetentionResult,
    ReadingMutationResult,
)
from app.modules.reading_activity.application.contracts import (
    ProjectActivityKind,
    ReadingActivityExportRecordResponse,
    ReadingActivityExportResponse,
    ReadingActivityPreferencesUpdateRequest,
    ReadingExportFormat,
    ReadingHourSnapshotRequest,
    ReadingInsightsRange,
    ReadingPageSnapshotRequest,
    ReadingPageInsightResponse,
    ReadingSessionResponse,
    ReadingSessionSnapshotRequest,
    ReadingSessionStartRequest,
    ReadingViewMode,
)
from app.bootstrap.adapters.reading_activity_project_activity_queries import (
    _ActivityItem,
    ProjectActivityRepository,
    _activity_cursor_fingerprint,
    _activity_document_destination,
    _activity_item_key,
    _page_activity_items,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingActivityPreference,
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
    ReadingSessionHour,
)
from app.modules.reading_activity.infrastructure.ledger_export import (
    ReadingLedgerExporter,
    _decode_position,
    _effective_page_detail_cutoff,
    _encode_position,
)
from app.bootstrap.adapters.reading_activity_mutations import (
    ReadingActivityMutationRepository,
    _snapshot_deltas,
    _validate_page_totals,
)
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_READING_ACTIVITY_COLUMNS,
)
from app.modules.papers.infrastructure.models import Document
from app.modules.reading_activity.infrastructure.rollup_mutations import (
    ReadingRollupWriter,
)
from app.bootstrap.adapters.reading_activity_project_insight_statements import (
    canonical_project_actor_count_statement as _canonical_project_actor_count_statement,
    complete_page_total_from_counts as _complete_page_total_from_counts,
    project_team_trend_statement as _project_team_trend_statement,
    qualified_project_pages_count_statement as _qualified_project_pages_count_statement,
    qualified_project_papers_count_statement as _qualified_project_papers_count_statement,
)
from app.modules.reading_activity.infrastructure.retention import (
    RETENTION_PAGE_ROW_BUDGET,
    SqlReadingActivityRetention,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
    _calendar_range_start,
    _range_start,
    _snapshot_digest,
)
from app.bootstrap.adapters.reading_activity_personal_queries import (
    _page_buckets,
    _paper_breakdown_hours_statement,
    _project_breakdown_hours_statement,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.transport.http.public_v1.reading_activity import _export_csv


NOW = datetime(2026, 8, 24, 8, 30, tzinfo=timezone.utc)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _actor(*, admin: bool = False) -> Actor:
    return Actor(
        id=41,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_admin=admin,
    )


def _session(*, visible_ms: int = 0, active_ms: int = 0) -> ReadingSession:
    return ReadingSession(
        id=uuid4(),
        user_id=41,
        document_id=uuid4(),
        project_id=None,
        view_mode="pdf",
        time_zone="UTC",
        metric_definition_version="active-reading-v1",
        revision=1,
        visible_ms=visible_ms,
        active_ms=active_ms,
        started_at=NOW - timedelta(seconds=10),
        last_seen_at=NOW,
        ended_at=None,
        last_snapshot_digest=None,
        contribute_to_project_aggregates=False,
        page_detail_purged_at=None,
    )


def _snapshot(
    *,
    revision: int = 2,
    visible_ms: int = 1_000,
    active_ms: int = 500,
    last_seen_at: datetime = NOW,
    ended_at: datetime | None = None,
    hours: list[ReadingHourSnapshotRequest] | None = None,
) -> ReadingSessionSnapshotRequest:
    if hours is None:
        hours = [
            ReadingHourSnapshotRequest(
                bucket_start=last_seen_at.astimezone(timezone.utc).replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                ),
                visible_ms=visible_ms,
                active_ms=active_ms,
            )
        ]
    return ReadingSessionSnapshotRequest(
        revision=revision,
        visible_ms=visible_ms,
        active_ms=active_ms,
        last_seen_at=last_seen_at,
        ended_at=ended_at,
        hours=hours,
        pages=[],
    )


def test_reading_activity_document_profile_loads_only_page_bounds() -> None:
    assert {column.key for column in DOCUMENT_READING_ACTIVITY_COLUMNS} == {
        "id",
        "page_count",
    }
    statement = select(Document).options(
        load_only(*DOCUMENT_READING_ACTIVITY_COLUMNS, raiseload=True)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "documents.page_count" in sql
    assert "documents.raw_content" not in sql
    assert "documents.page_offset_map" not in sql


def test_paper_insights_requests_the_reading_activity_document_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExpectedAccessStop(Exception):
        pass

    def require_access(*args: object, **kwargs: object) -> None:
        del args
        assert kwargs["document_columns"] is DOCUMENT_READING_ACTIVITY_COLUMNS
        raise ExpectedAccessStop

    monkeypatch.setattr(
        "app.bootstrap.adapters.reading_activity_paper_queries.require_document_access",
        require_access,
    )

    with pytest.raises(ExpectedAccessStop):
        PaperInsightsRepository(MagicMock(), clock=FrozenClock()).paper_insights(
            actor=_actor(),
            document_id=uuid4(),
            insight_range=ReadingInsightsRange.ALL,
            time_zone="UTC",
        )


def test_page_bucket_boundaries_match_sql_for_non_divisible_page_count() -> None:
    buckets = _page_buckets(
        maximum_page=21,
        bucket_values={0: 300, 1: 200, 19: 100},
    )

    assert len(buckets) == 20
    assert (buckets[0].start_page, buckets[0].end_page) == (1, 2)
    assert (buckets[1].start_page, buckets[1].end_page) == (3, 3)
    assert (buckets[-1].start_page, buckets[-1].end_page) == (21, 21)
    assert sum(bucket.active_ms for bucket in buckets) == 600


def test_calendar_ranges_use_local_days_and_first_complete_utc_hour() -> None:
    assert _range_start(
        ReadingInsightsRange.SEVEN_DAYS,
        NOW,
        time_zone="Asia/Shanghai",
    ) == datetime(2026, 8, 17, 16, tzinfo=timezone.utc)

    kathmandu_calendar_start = _calendar_range_start(
        ReadingInsightsRange.SEVEN_DAYS,
        NOW,
        time_zone="Asia/Kathmandu",
    )
    assert kathmandu_calendar_start == datetime(
        2026, 8, 17, 18, 15, tzinfo=timezone.utc
    )
    assert _range_start(
        ReadingInsightsRange.SEVEN_DAYS,
        NOW,
        time_zone="Asia/Kathmandu",
    ) == datetime(2026, 8, 17, 19, tzinfo=timezone.utc)
    assert _range_start(
        ReadingInsightsRange.SEVEN_DAYS,
        NOW,
        time_zone="UTC",
    ) == datetime(2026, 8, 18, tzinfo=timezone.utc)


def test_reading_data_since_excludes_future_skew_and_completeness_uses_launch() -> None:
    launch = NOW - timedelta(days=60)
    db = MagicMock()
    db.scalar.return_value = None
    db.get.return_value = SimpleNamespace(collection_started_at=launch)
    repository = ReadingActivityRepositoryBase(db, clock=FrozenClock())

    assert repository._reading_data_since(user_id=41) is None  # noqa: SLF001
    statement = str(db.scalar.call_args.args[0])
    assert "reading_sessions.started_at <=" in statement
    assert (
        repository._activity_history_complete_since()  # noqa: SLF001
        == launch
    )


def test_page_snapshot_requires_exact_segment_sum_and_bounded_session() -> None:
    with pytest.raises(ValidationError, match="vertical segment durations"):
        ReadingPageSnapshotRequest(
            page_number=1,
            visible_ms=20,
            active_ms=20,
            visit_count=1,
            vertical_segments_ms=[0] * 20,
        )

    with pytest.raises(ValidationError):
        _snapshot(visible_ms=24 * 60 * 60 * 1_000 + 1)

    with pytest.raises(ValidationError):
        _snapshot(revision=2_147_483_648)

    with pytest.raises(ValidationError):
        ReadingSessionStartRequest(
            session_id=uuid4(),
            view_mode=ReadingViewMode.PDF,
            started_at=NOW,
            time_zone="UTC",
            metric_definition_version="x" * 65,
        )

    with pytest.raises(ValidationError):
        ReadingPageInsightResponse(
            page_number=1,
            active_ms=0,
            visible_ms=0,
            visit_count=0,
            vertical_segments_ms=[0] * 19,
        )


def test_snapshot_timing_uses_one_cumulative_tolerance_not_one_per_revision() -> None:
    model = _session(visible_ms=10_000, active_ms=5_000)
    with pytest.raises(AppError) as error:
        _snapshot_deltas(
            model=model,
            request=_snapshot(visible_ms=20_001, active_ms=5_000),
            now=NOW,
        )
    assert error.value.code == "reading_session_duration_invalid"

    with pytest.raises(AppError) as future_error:
        _snapshot_deltas(
            model=model,
            request=_snapshot(
                visible_ms=10_000,
                active_ms=5_000,
                ended_at=NOW + timedelta(minutes=6),
            ),
            now=NOW,
        )
    assert future_error.value.code == "reading_session_time_invalid"


def test_client_hour_buckets_are_exact_across_boundaries_and_hidden_gaps() -> None:
    started_at = NOW.replace(hour=5, minute=59)
    last_seen_at = NOW.replace(hour=8, minute=1)
    model = _session()
    model.started_at = started_at
    model.last_seen_at = started_at
    request = _snapshot(
        visible_ms=62_000,
        active_ms=31_000,
        last_seen_at=last_seen_at,
        hours=[
            ReadingHourSnapshotRequest(
                bucket_start=started_at.replace(minute=0),
                visible_ms=1_000,
                active_ms=500,
            ),
            ReadingHourSnapshotRequest(
                bucket_start=last_seen_at.replace(minute=0),
                visible_ms=61_000,
                active_ms=30_500,
            ),
        ],
    )

    assert sum(hour.visible_ms for hour in request.hours) == request.visible_ms
    assert _snapshot_deltas(model=model, request=request, now=last_seen_at) == (
        62_000,
        31_000,
    )


def test_hour_bucket_cannot_hide_a_full_day_inside_one_hour() -> None:
    started_at = NOW - timedelta(hours=23)
    model = _session()
    model.started_at = started_at
    model.last_seen_at = started_at
    request = _snapshot(
        visible_ms=23 * 60 * 60 * 1_000,
        active_ms=1_000,
        last_seen_at=NOW,
        hours=[
            ReadingHourSnapshotRequest(
                bucket_start=NOW.replace(minute=0),
                visible_ms=23 * 60 * 60 * 1_000,
                active_ms=1_000,
            )
        ],
    )

    with pytest.raises(AppError) as error:
        _snapshot_deltas(model=model, request=request, now=NOW)
    assert error.value.code == "reading_session_hour_duration_invalid"


def test_snapshot_digest_is_idempotent_and_page_totals_span_partial_chunks() -> None:
    request = _snapshot(revision=7, visible_ms=60_000, active_ms=30_000)
    assert _snapshot_digest(request) == _snapshot_digest(request.model_copy())
    assert _snapshot_digest(request) != _snapshot_digest(
        request.model_copy(update={"revision": 8})
    )

    with pytest.raises(AppError) as error:
        _validate_page_totals(
            # This represents the database sum after multiple page chunks,
            # not merely the pages in the latest request.
            page_visible_ms=60_001,
            page_active_ms=30_001,
            request=request,
        )
    assert error.value.code == "reading_session_page_totals_invalid"


@pytest.mark.parametrize("contribute", [False, True])
def test_project_contribution_is_frozen_without_materializing_lost_start_rollups(
    monkeypatch: pytest.MonkeyPatch,
    contribute: bool,
) -> None:
    db = MagicMock()
    preference = SimpleNamespace(
        recording_enabled=True,
        contribute_anonymous_project_aggregates=contribute,
        updated_at=NOW,
    )

    def get(model: object, key: object) -> object | None:
        del key
        if model is ReadingActivityPreference:
            return preference
        return None

    db.get.side_effect = get

    def require_access(*args: object, **kwargs: object) -> object:
        del args
        assert kwargs["document_columns"] is DOCUMENT_READING_ACTIVITY_COLUMNS
        return object()

    monkeypatch.setattr(
        "app.bootstrap.adapters.reading_activity_mutations.require_document_access",
        require_access,
    )
    project_id = uuid4()
    result = ReadingActivityMutationRepository(db, clock=FrozenClock()).start_session(
        actor=_actor(),
        document_id=uuid4(),
        request=ReadingSessionStartRequest(
            session_id=uuid4(),
            project_id=project_id,
            view_mode=ReadingViewMode.PDF,
            started_at=NOW,
            time_zone="UTC",
        ),
    )

    assert result.value.project_contribution_enabled is contribute
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, ReadingSession) for item in added)
    assert not any(isinstance(item, ReadingPersonalHourRollup) for item in added)
    assert not any(isinstance(item, ReadingProjectHourRollup) for item in added)
    user_lock = db.execute.call_args_list[0].args[0]
    assert "pg_advisory_xact_lock" in str(user_lock)
    assert "reading-activity-user:41" in user_lock.compile().params.values()


def test_session_update_requests_the_reading_activity_document_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExpectedAccessStop(Exception):
        pass

    model = _session()
    db = MagicMock()
    db.scalar.return_value = model

    def get_access(*args: object, **kwargs: object) -> None:
        del args
        assert kwargs["document_columns"] is DOCUMENT_READING_ACTIVITY_COLUMNS
        raise ExpectedAccessStop

    monkeypatch.setattr(
        "app.bootstrap.adapters.reading_activity_mutations.get_document_access",
        get_access,
    )

    with pytest.raises(ExpectedAccessStop):
        ReadingActivityMutationRepository(db, clock=FrozenClock()).update_session(
            actor=_actor(),
            session_id=model.id,
            request=_snapshot(),
        )


def test_session_start_replay_survives_later_opt_out_and_access_loss() -> None:
    existing = _session()
    existing.revision = 0
    existing.started_at = NOW
    existing.last_seen_at = NOW
    existing.ended_at = NOW
    db = MagicMock()
    db.get.side_effect = lambda model, key: (
        existing if model is ReadingSession and key == existing.id else None
    )

    result = ReadingActivityMutationRepository(db, clock=FrozenClock()).start_session(
        actor=_actor(),
        document_id=existing.document_id,
        request=ReadingSessionStartRequest(
            session_id=existing.id,
            view_mode=ReadingViewMode.PDF,
            started_at=NOW,
            time_zone="UTC",
        ),
    )

    assert result.changed is False
    assert result.value.id == existing.id
    assert result.value.ended_at == NOW
    assert not any(
        call.args[0] is ReadingActivityPreference for call in db.get.call_args_list
    )


def test_contribution_opt_out_closes_open_team_sessions_under_user_lock() -> None:
    current = SimpleNamespace(
        recording_enabled=True,
        contribute_anonymous_project_aggregates=True,
        updated_at=NOW,
    )
    updated = SimpleNamespace(
        recording_enabled=True,
        contribute_anonymous_project_aggregates=False,
        updated_at=NOW,
    )
    db = MagicMock()
    db.get.return_value = current
    db.execute.return_value.scalar_one.return_value = updated

    result = ReadingActivityMutationRepository(
        db, clock=FrozenClock()
    ).update_preferences(
        user_id=41,
        request=ReadingActivityPreferencesUpdateRequest(
            recording_enabled=True,
            contribute_anonymous_project_aggregates=False,
        ),
    )

    assert result.changed is True
    assert result.value.contribute_anonymous_project_aggregates is False
    assert current.contribute_anonymous_project_aggregates is False
    assert "pg_advisory_xact_lock" in str(db.execute.call_args_list[0].args[0])
    close_sql = str(db.execute.call_args_list[1].args[0])
    assert close_sql.startswith("UPDATE scholens.reading_sessions")
    assert "reading_sessions.ended_at IS NULL" in close_sql
    assert "reading_sessions.project_id IS NOT NULL" in close_sql
    assert "ended_at=scholens.reading_sessions.last_seen_at" in close_sql


def test_contribution_enable_closes_existing_private_project_sessions() -> None:
    current = SimpleNamespace(
        recording_enabled=True,
        contribute_anonymous_project_aggregates=False,
        updated_at=NOW,
    )
    db = MagicMock()
    db.get.return_value = current

    result = ReadingActivityMutationRepository(
        db, clock=FrozenClock()
    ).update_preferences(
        user_id=41,
        request=ReadingActivityPreferencesUpdateRequest(
            recording_enabled=True,
            contribute_anonymous_project_aggregates=True,
        ),
    )

    assert result.value.contribute_anonymous_project_aggregates is True
    close_sql = str(db.execute.call_args_list[1].args[0])
    assert "reading_sessions.project_id IS NOT NULL" in close_sql
    assert "WHERE scholens.reading_sessions.user_id" in close_sql


def test_closed_session_rejects_future_revision_but_replays_lost_ack() -> None:
    accepted = _snapshot(revision=2, visible_ms=1_000, active_ms=500)
    model = _session(visible_ms=accepted.visible_ms, active_ms=accepted.active_ms)
    model.revision = accepted.revision
    model.last_snapshot_digest = _snapshot_digest(accepted)
    model.ended_at = model.last_seen_at
    db = MagicMock()
    db.scalar.return_value = model
    repository = ReadingActivityMutationRepository(db, clock=FrozenClock())

    replay = repository.update_session(
        actor=_actor(),
        session_id=model.id,
        request=accepted,
    )
    assert replay.changed is False

    with pytest.raises(AppError) as error:
        repository.update_session(
            actor=_actor(),
            session_id=model.id,
            request=accepted.model_copy(update={"revision": 3}),
        )
    assert error.value.code == "reading_session_ended"


def test_session_revision_must_advance_contiguously() -> None:
    model = _session(visible_ms=0, active_ms=0)
    model.revision = 1
    db = MagicMock()
    db.scalar.return_value = model

    with pytest.raises(AppError) as error:
        ReadingActivityMutationRepository(db, clock=FrozenClock()).update_session(
            actor=_actor(),
            session_id=model.id,
            request=_snapshot(revision=3),
        )

    assert error.value.code == "reading_session_revision_gap"


def test_rollup_snapshot_bulk_preloads_each_involved_table_once() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    model = _session()
    model.project_id = uuid4()
    model.contribute_to_project_aggregates = True

    ReadingRollupWriter(db).apply_snapshots(
        model=model,
        hours=[
            ReadingHourSnapshotRequest(
                bucket_start=NOW.replace(minute=0),
                visible_ms=1_000,
                active_ms=500,
            )
        ],
        pages=[
            ReadingPageSnapshotRequest(
                page_number=page_number,
                visible_ms=10,
                active_ms=5,
                visit_count=1,
                vertical_segments_ms=[5, *([0] * 19)],
            )
            for page_number in range(1, 101)
        ],
        materialize_session_count=True,
    )

    db.get.assert_not_called()
    # session/personal/project hours plus session/personal/private-project/team pages
    assert db.scalars.call_count == 7


def test_passive_project_page_deletion_needs_no_zero_active_rollup() -> None:
    db = MagicMock()
    writer = ReadingRollupWriter(db)

    writer._subtract_project_page_rollup(  # noqa: SLF001
        row=None,
        active_ms=0,
    )

    db.delete.assert_not_called()
    with pytest.raises(RuntimeError, match="reading_project_page_rollup_missing"):
        writer._subtract_project_page_rollup(  # noqa: SLF001
            row=None,
            active_ms=1,
        )


def test_new_all_zero_page_snapshot_does_not_materialize_empty_rows() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    ReadingRollupWriter(db).apply_snapshots(
        model=_session(),
        hours=[],
        pages=[
            ReadingPageSnapshotRequest(
                page_number=10_000,
                visible_ms=0,
                active_ms=0,
                visit_count=0,
                vertical_segments_ms=[0] * 20,
            )
        ],
        materialize_session_count=False,
    )

    db.add.assert_not_called()


def test_zero_duration_project_session_does_not_materialize_team_hour_row() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    model = _session()
    model.project_id = uuid4()
    model.contribute_to_project_aggregates = True

    ReadingRollupWriter(db).apply_snapshots(
        model=model,
        hours=[
            ReadingHourSnapshotRequest(
                bucket_start=NOW.replace(minute=0),
                visible_ms=0,
                active_ms=0,
            )
        ],
        pages=[],
        materialize_session_count=True,
    )

    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, ReadingPersonalHourRollup) for item in added)
    assert not any(isinstance(item, ReadingProjectHourRollup) for item in added)


def test_deleting_zero_duration_project_session_does_not_leave_team_hour_row() -> None:
    db = MagicMock()
    model = _session()
    model.project_id = uuid4()
    model.contribute_to_project_aggregates = True
    source_hour = ReadingSessionHour(
        session_id=model.id,
        metric_definition_version=model.metric_definition_version,
        bucket_start=NOW.replace(minute=0),
        visible_ms=0,
        active_ms=0,
        session_count=1,
    )

    def result(rows: list[object]) -> MagicMock:
        value = MagicMock()
        value.all.return_value = rows
        return value

    db.scalars.side_effect = [
        result([source_hour]),
        result([]),
        result([]),
    ]

    ReadingRollupWriter(db).subtract_session(
        model=model,
        personal=False,
        personal_project_id=None,
        team_project_id=model.project_id,
    )

    added = [call.args[0] for call in db.add.call_args_list]
    assert not any(isinstance(item, ReadingProjectHourRollup) for item in added)


def test_private_project_privacy_hides_two_reader_side_channels() -> None:
    sql = str(
        _project_team_trend_statement(
            project_id=uuid4(),
            document_ids={uuid4()},
            start=NOW - timedelta(days=7),
            end=NOW,
        ).compile(compile_kwargs={"literal_binds": True})
    )

    assert "CASE WHEN (scholens.reading_project_hour_rollups.active_ms > 0)" in sql
    assert "count(distinct" in sql.lower()
    assert ">= 3" in sql
    assert "HAVING" in sql


def test_canonical_collaborator_count_cannot_reveal_reading_member_overlap() -> None:
    sql = str(
        _canonical_project_actor_count_statement(
            project_id=uuid4(),
            fact_start=NOW - timedelta(days=30),
        )
    )

    assert "reading_project_hour_rollups" not in sql
    assert "project_collaborators" in sql
    assert "annotation_comments" in sql


def test_project_coverage_requires_every_paper_page_count() -> None:
    assert _complete_page_total_from_counts(total=2, known=1, page_total=10) is None
    assert _complete_page_total_from_counts(total=2, known=2, page_total=15) == 15


def test_k_anonymous_paper_and_page_queries_exclude_zero_active_rows() -> None:
    project_id = uuid4()
    paper_sql = str(
        _qualified_project_papers_count_statement(
            project_id=project_id,
            document_ids={uuid4()},
            start=NOW - timedelta(days=7),
            end=NOW,
        ).compile(compile_kwargs={"literal_binds": True})
    )
    page_sql = str(
        _qualified_project_pages_count_statement(
            project_id=project_id,
            document_ids={uuid4()},
        ).compile(compile_kwargs={"literal_binds": True})
    )

    assert "reading_project_hour_rollups.active_ms > 0" in paper_sql
    assert "reading_project_hour_rollups.user_id)) >= 3" in paper_sql
    assert "reading_project_page_rollups.active_ms > 0" in page_sql
    assert "reading_project_page_rollups.user_id)) >= 3" in page_sql


def test_range_breakdowns_are_sourced_from_the_same_hour_cohort_as_trends() -> None:
    project_sql = str(
        _project_breakdown_hours_statement(
            user_id=41,
            start=NOW - timedelta(days=30),
            end=NOW,
        )
    )
    paper_sql = str(
        _paper_breakdown_hours_statement(
            user_id=41,
            start=NOW - timedelta(days=30),
            end=NOW,
        )
    )

    assert "reading_session_hours" in project_sql
    assert "reading_session_hours.bucket_start >=" in project_sql
    assert "reading_sessions.active_ms" not in project_sql
    assert "reading_personal_hour_rollups.bucket_start >=" in paper_sql
    assert "sum(scholens.reading_personal_hour_rollups.active_ms)" in paper_sql


def test_export_cursor_position_round_trip_and_validation() -> None:
    values = _encode_position(
        exported_at=NOW,
        record_type="session_hour",
        key=(str(uuid4()), NOW.isoformat()),
    )
    assert _decode_position(values) == (
        NOW,
        "session_hour",
        (values[2], values[3]),
    )
    with pytest.raises(AppError):
        _decode_position((NOW.isoformat(), "unknown", "x", "", "", ""))

    codec = SignedCursorCodec(
        "test-reading-export-cursor-secret-32-bytes",
        revision="reading-activity-export-v1",
        error_code="reading_activity_export_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    cursor = codec.encode_keyset(fingerprint="actor=41;format=json", values=values)
    assert (
        codec.decode_keyset(
            cursor=cursor,
            fingerprint="actor=41;format=json",
            arity=6,
        )
        == values
    )
    with pytest.raises(AppError):
        codec.decode_keyset(
            cursor=cursor,
            fingerprint="actor=42;format=json",
            arity=6,
        )


def test_project_activity_keyset_has_no_gap_at_equal_timestamps() -> None:
    ids = [
        f"paper:{uuid4()}",
        f"member:{uuid4()}",
        f"research:{uuid4()}",
        f"comment:{uuid4()}",
        f"resolved:{uuid4()}",
    ]
    kinds = list(ProjectActivityKind)
    source = [
        _ActivityItem(id=item_id, kind=kinds[index], occurred_at=NOW)
        for index, item_id in enumerate(ids)
    ]
    expected = [
        item.id for item in sorted(source, key=_activity_item_key, reverse=True)
    ]
    collected: list[str] = []
    cursor_key = None

    while True:
        page, has_more = _page_activity_items(
            source,
            limit=2,
            cursor_key=cursor_key,
        )
        collected.extend(item.id for item in page)
        if not has_more:
            break
        cursor_key = _activity_item_key(page[-1])

    assert collected == expected
    assert len(collected) == len(set(collected))
    assert has_more is False


def test_project_activity_cursor_is_signed_and_bound_to_actor_and_project() -> None:
    project_id = uuid4()
    codec = SignedCursorCodec(
        "test-project-activity-cursor-secret-32-bytes",
        revision="project-activity-v1",
        error_code="project_activity_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    fingerprint = _activity_cursor_fingerprint(
        actor_id=41,
        project_id=project_id,
    )
    cursor = codec.encode_keyset(
        fingerprint=fingerprint,
        values=(NOW.isoformat(), f"paper:{uuid4()}"),
    )

    assert (
        len(codec.decode_keyset(cursor=cursor, fingerprint=fingerprint, arity=2)) == 2
    )
    with pytest.raises(AppError):
        codec.decode_keyset(
            cursor=cursor,
            fingerprint=_activity_cursor_fingerprint(
                actor_id=41,
                project_id=uuid4(),
            ),
            arity=2,
        )
    tamper_at = len(cursor) // 2
    tampered = (
        cursor[:tamper_at]
        + ("A" if cursor[tamper_at] != "A" else "B")
        + cursor[tamper_at + 1 :]
    )
    with pytest.raises(AppError):
        codec.decode_keyset(
            cursor=tampered,
            fingerprint=fingerprint,
            arity=2,
        )


def test_project_feed_hides_removed_document_destination_and_title() -> None:
    document_id = uuid4()
    item = _ActivityItem(
        id=f"research:{uuid4()}",
        kind=ProjectActivityKind.OUTPUT_CREATED,
        occurred_at=NOW,
        document_id=document_id,
    )

    assert _activity_document_destination(item, {}) == (None, None)
    assert _activity_document_destination(item, {document_id: "Paper"}) == (
        document_id,
        "Paper",
    )

    db = MagicMock()
    db.execute.return_value.all.return_value = []
    ProjectActivityRepository(db, clock=FrozenClock())._document_titles(  # noqa: SLF001
        [item],
        actor_id=41,
    )
    sql = str(db.execute.call_args.args[0])
    assert "library_papers" in sql
    assert "project_papers" in sql
    assert "project_collaborators" in sql


def test_export_page_detail_cutoff_only_moves_forward_across_pages() -> None:
    assert _effective_page_detail_cutoff(
        exported_at=NOW,
        now=NOW + timedelta(days=91),
    ) == NOW + timedelta(days=1)


def test_old_export_cursor_uses_current_privacy_cutoff() -> None:
    exported_at = NOW - timedelta(days=91)
    codec = SignedCursorCodec(
        "test-reading-export-cursor-secret-32-bytes",
        revision="reading-activity-export-v1",
        error_code="reading_activity_export_cursor_invalid",
        error_kind=FailureKind.INVALID_ARGUMENT,
    )
    cursor = codec.encode_keyset(
        fingerprint="actor=41;format=json",
        values=_encode_position(
            exported_at=exported_at,
            record_type="session",
            key=(str(uuid4()),),
        ),
    )

    class CapturingExporter(ReadingLedgerExporter):
        cutoffs: list[datetime] = []

        def _batch(self, **kwargs):  # type: ignore[no-untyped-def]
            self.cutoffs.append(kwargs["page_detail_cutoff"])
            return []

    exporter = CapturingExporter(MagicMock(), clock=FrozenClock(), cursors=codec)
    response = exporter.export(
        actor=_actor(),
        export_format=ReadingExportFormat.JSON,
        cursor=cursor,
        limit=10,
    )

    assert response.exported_at == exported_at
    assert exporter.cutoffs
    assert set(exporter.cutoffs) == {NOW - timedelta(days=90)}


def test_export_last_phase_has_stable_native_key_and_payload() -> None:
    row = SimpleNamespace(
        project_id=uuid4(),
        document_id=uuid4(),
        metric_definition_version="active-reading-v1",
        bucket_start=NOW.replace(minute=0),
        visible_ms=60_000,
        active_ms=30_000,
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [row]
    exporter = ReadingLedgerExporter(
        db,
        clock=FrozenClock(),
        cursors=SignedCursorCodec(
            "test-reading-export-cursor-secret-32-bytes",
            revision="reading-activity-export-v1",
            error_code="reading_activity_export_cursor_invalid",
        ),
    )

    entries = exporter._project_hours(  # noqa: SLF001
        actor_id=41,
        after=None,
        limit=2,
    )

    assert len(entries) == 1
    assert entries[0].record_type == "project_contributed_hour_rollup"
    assert entries[0].key == (
        str(row.project_id),
        str(row.document_id),
        "active-reading-v1",
        row.bucket_start.isoformat(),
    )
    assert entries[0].payload["active_ms"] == 30_000
    sql = str(db.scalars.call_args.args[0])
    assert "reading_project_hour_rollups.user_id" in sql
    assert "ORDER BY scholens.reading_project_hour_rollups.project_id" in sql


def test_session_start_is_not_duplicated_into_operation_journal() -> None:
    gateway = MagicMock()
    response = ReadingSessionResponse(
        id=uuid4(),
        document_id=uuid4(),
        project_id=None,
        view_mode=ReadingViewMode.PDF,
        time_zone="UTC",
        metric_definition_version="active-reading-v1",
        revision=0,
        visible_ms=0,
        active_ms=0,
        started_at=NOW,
        last_seen_at=NOW,
        ended_at=None,
        project_contribution_enabled=False,
        page_detail_available=True,
    )
    gateway.start_session.return_value = ReadingMutationResult(response, True)
    journal = MagicMock()

    result = ReadingActivity(gateway, journal=journal).start_session(
        actor=_actor(),
        document_id=response.document_id,
        request=ReadingSessionStartRequest(
            session_id=response.id,
            view_mode=ReadingViewMode.PDF,
            started_at=NOW,
            time_zone="UTC",
        ),
    )

    assert result == response
    journal.append.assert_not_called()


def test_retention_is_admin_guarded_journaled_and_bounded() -> None:
    gateway = MagicMock()
    gateway.purge_session_pages.return_value = ReadingActivityRetentionResult(
        cutoff=NOW - timedelta(days=90),
        candidates=4,
        purged_sessions=2,
        purged_pages=17,
    )
    journal = MagicMock()
    maintenance = ReadingActivityRetention(
        gateway,
        journal=journal,
        clock=FrozenClock(),
    )

    result = maintenance.purge_session_pages(
        actor=_actor(admin=True),
        operation=MagicMock(),
        retention_days=90,
        batch_size=2,
        apply=True,
    )

    assert result.purged_pages == 17
    gateway.purge_session_pages.assert_called_once_with(
        cutoff=NOW - timedelta(days=90),
        batch_size=2,
        apply=True,
    )
    journal.append.assert_called_once()
    with pytest.raises(AppError):
        maintenance.purge_session_pages(
            actor=_actor(),
            operation=MagicMock(),
            retention_days=90,
            batch_size=2,
            apply=False,
        )


def test_retention_adapter_dry_run_does_not_delete() -> None:
    db = MagicMock()
    db.scalar.return_value = 3

    result = SqlReadingActivityRetention(db).purge_session_pages(
        cutoff=NOW - timedelta(days=90),
        batch_size=2,
        apply=False,
    )

    assert result.candidates == 3
    assert result.purged_sessions == 0
    candidate_sql = str(db.scalar.call_args.args[0])
    assert "reading_sessions.started_at <" in candidate_sql
    assert "reading_sessions.last_seen_at <" not in candidate_sql
    db.execute.assert_not_called()


def test_retention_scan_uses_partial_started_at_index() -> None:
    table = cast(Table, ReadingSession.__table__)
    index = next(
        item
        for item in table.indexes
        if item.name == "ix_reading_sessions_page_detail_retention"
    )

    assert [column.name for column in index.columns] == ["started_at"]
    assert (
        str(index.dialect_options["postgresql"]["where"])
        == "page_detail_purged_at IS NULL"
    )


def test_document_cascade_foreign_keys_have_leading_indexes_in_model_and_migration() -> (
    None
):
    expected = {
        ReadingSession: "ix_reading_sessions_document_id",
        ReadingPersonalPageRollup: "ix_reading_personal_page_rollups_document_id",
        ReadingProjectPageRollup: "ix_reading_project_page_rollups_document_id",
        ReadingProjectPersonalPageRollup: (
            "ix_reading_project_personal_page_rollups_document_id"
        ),
        ReadingPersonalHourRollup: "ix_reading_personal_hour_rollups_document_id",
        ReadingProjectHourRollup: "ix_reading_project_hour_rollups_document_id",
    }
    for model, index_name in expected.items():
        index = next(
            item for item in model.__table__.indexes if item.name == index_name
        )
        assert [column.name for column in index.columns] == ["document_id"]

    migration = (
        Path(__file__).parents[1]
        / "migrations/versions/2026_08_24_1700_reading_activity_ledger.py"
    ).read_text(encoding="utf-8")
    assert "ix_reading_sessions_document_id" in migration
    assert migration.count('f"ix_{table}_document_id"') == 2


def test_retention_adapter_marks_and_purges_one_bounded_batch() -> None:
    db = MagicMock()
    session_ids = [uuid4(), uuid4()]
    db.scalar.return_value = 4
    db.scalars.return_value.all.return_value = session_ids
    db.execute.return_value.all.return_value = [
        (session_ids[0], 8),
        (session_ids[1], 9),
    ]

    result = SqlReadingActivityRetention(db).purge_session_pages(
        cutoff=NOW - timedelta(days=90),
        batch_size=2,
        apply=True,
    )

    assert result.candidates == 4
    assert result.purged_sessions == 2
    assert result.purged_pages == 17
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any(
        "DELETE FROM scholens.reading_session_pages" in item for item in statements
    )
    assert any("UPDATE scholens.reading_sessions" in item for item in statements)
    lock_sql = str(db.scalars.call_args.args[0])
    assert "ORDER BY scholens.reading_sessions.id" in lock_sql


def test_retention_batch_is_bounded_by_page_rows_not_only_session_count() -> None:
    db = MagicMock()
    session_ids = [uuid4() for _ in range(6)]
    db.scalar.return_value = len(session_ids)
    db.scalars.return_value.all.return_value = session_ids
    db.execute.return_value.all.return_value = [
        (session_id, 10_000) for session_id in session_ids
    ]

    result = SqlReadingActivityRetention(db).purge_session_pages(
        cutoff=NOW - timedelta(days=90),
        batch_size=100,
        apply=True,
    )

    assert result.purged_pages == RETENTION_PAGE_ROW_BUDGET
    assert result.purged_sessions == RETENTION_PAGE_ROW_BUDGET // 10_000


def test_scoped_delete_uses_actor_owned_ledger_without_current_paper_access() -> None:
    db = MagicMock()
    db.scalar.return_value = 2
    document_id = uuid4()

    deleted = ReadingActivityMutationRepository(db, clock=FrozenClock()).delete_paper(
        actor=_actor(),
        document_id=document_id,
    )

    assert deleted == 2
    user_lock = db.execute.call_args_list[0].args[0]
    assert "pg_advisory_xact_lock" in str(user_lock)
    assert "reading-activity-user:41" in user_lock.compile().params.values()
    statement = next(
        str(call.args[0])
        for call in db.execute.call_args_list
        if "DELETE FROM scholens.reading_sessions" in str(call.args[0])
    )
    _assert_broad_erasure_locks_sessions_in_id_order(statement)


def test_delete_all_serializes_with_new_session_start_and_locks_heartbeats() -> None:
    db = MagicMock()
    db.scalar.return_value = 1

    deleted = ReadingActivityMutationRepository(db, clock=FrozenClock()).delete_all(
        actor=_actor()
    )

    assert deleted == 1
    user_lock = db.execute.call_args_list[0].args[0]
    assert "reading-activity-user:41" in user_lock.compile().params.values()
    statement = next(
        str(call.args[0])
        for call in db.execute.call_args_list
        if "DELETE FROM scholens.reading_sessions" in str(call.args[0])
    )
    _assert_broad_erasure_locks_sessions_in_id_order(statement)


def test_project_contribution_delete_closes_open_session_before_detaching() -> None:
    db = MagicMock()
    project_id = uuid4()
    db.scalar.return_value = 1

    deleted = ReadingActivityMutationRepository(
        db, clock=FrozenClock()
    ).delete_project_contribution(actor=_actor(), project_id=project_id)

    assert deleted == 1
    user_lock = db.execute.call_args_list[0].args[0]
    assert "reading-activity-user:41" in user_lock.compile().params.values()
    update_sql = next(
        str(call.args[0])
        for call in db.execute.call_args_list
        if "UPDATE scholens.reading_sessions" in str(call.args[0])
    )
    _assert_broad_erasure_locks_sessions_in_id_order(update_sql)
    assert "project_id=" in update_sql
    assert "contribute_to_project_aggregates=" in update_sql


def _assert_broad_erasure_locks_sessions_in_id_order(statement: str) -> None:
    assert statement.startswith("WITH locked_reading_sessions AS")
    assert "ORDER BY scholens.reading_sessions.id FOR UPDATE" in statement
    assert "SELECT locked_reading_sessions.id" in statement


def test_expired_single_session_delete_fails_instead_of_drifting_rollups() -> None:
    db = MagicMock()
    model = _session()
    model.page_detail_purged_at = NOW
    db.scalar.return_value = model

    with pytest.raises(AppError) as error:
        ReadingActivityMutationRepository(db, clock=FrozenClock()).delete_session(
            actor=_actor(),
            session_id=model.id,
        )

    assert error.value.code == "reading_session_detail_expired"
    user_lock = db.execute.call_args_list[0].args[0]
    assert "reading-activity-user:41" in user_lock.compile().params.values()
    db.delete.assert_not_called()


def test_csv_export_is_normalized_and_header_is_optional() -> None:
    exported = ReadingActivityExportResponse(
        exported_at=NOW,
        records=[
            ReadingActivityExportRecordResponse(
                record_type="session",
                payload={
                    "metric_definition_version": "active-reading-v1",
                    "time_zone": "Asia/Shanghai",
                    "page_detail_available": False,
                },
            )
        ],
        next_cursor="next",
    )

    csv_text = _export_csv(exported, include_header=True)
    without_header = _export_csv(exported, include_header=False)

    header, row = csv_text.splitlines()
    assert header == "record_type,payload_json"
    assert row == without_header.strip()
    assert "active-reading-v1" in row
    assert "Asia/Shanghai" in row


def test_public_contract_mounts_authenticated_json_and_csv_export() -> None:
    schema = create_app().openapi()
    export = schema["paths"]["/api/v1/me/reading-activity/export"]["get"]
    assert export["security"] == [{"BearerAuth": []}]
    assert set(export["responses"]["200"]["content"]) == {
        "application/json",
        "text/csv",
    }
    assert "/api/v1/me/reading-activity/paper-summaries" in schema["paths"]
