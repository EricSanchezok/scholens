"""Hourly scheduler drains retention and schedules Zotero only when due."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests

from src import schedule_maintenance


def _response(body: dict[str, int]) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = "https://server.example/internal/v1/schedules/test"
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()  # noqa: SLF001 - response fixture
    response._content_consumed = True  # noqa: SLF001 - response fixture
    return response


def test_retention_schedule_repeats_bounded_transactions_until_empty() -> None:
    with patch(
        "src.schedule_maintenance.post_signed_json",
        side_effect=[
            _response(
                {
                    "purged_sessions": 100,
                    "purged_pages": 8000,
                    "remaining_candidates": 2,
                }
            ),
            _response(
                {
                    "purged_sessions": 2,
                    "purged_pages": 3,
                    "remaining_candidates": 0,
                }
            ),
        ],
    ) as post:
        schedule_maintenance._drain_reading_activity_retention(  # noqa: SLF001
            "https://server.example"
        )

    assert post.call_count == 2
    assert all(
        call.args[0].endswith(
            "/internal/v1/schedules/reading-activity-retention?batch_size=100"
        )
        for call in post.call_args_list
    )


def test_retention_schedule_retries_locked_rows_then_reports_no_progress() -> None:
    with (
        patch(
            "src.schedule_maintenance.post_signed_json",
            return_value=_response(
                {
                    "purged_sessions": 0,
                    "purged_pages": 0,
                    "remaining_candidates": 3,
                }
            ),
        ) as post,
        patch("src.schedule_maintenance.time.sleep") as sleep,
        pytest.raises(RuntimeError, match="reading_activity_retention_no_progress"),
    ):
        schedule_maintenance._drain_reading_activity_retention(  # noqa: SLF001
            "https://server.example"
        )

    assert post.call_count == schedule_maintenance.MAX_RETENTION_NO_PROGRESS_ATTEMPTS
    assert [call.args[0] for call in sleep.call_args_list] == [0.25, 0.5]


def test_retention_schedule_recovers_after_transient_locked_rows() -> None:
    with (
        patch(
            "src.schedule_maintenance.post_signed_json",
            side_effect=[
                _response(
                    {
                        "purged_sessions": 0,
                        "purged_pages": 0,
                        "remaining_candidates": 3,
                    }
                ),
                _response(
                    {
                        "purged_sessions": 3,
                        "purged_pages": 21,
                        "remaining_candidates": 0,
                    }
                ),
            ],
        ) as post,
        patch("src.schedule_maintenance.time.sleep") as sleep,
    ):
        schedule_maintenance._drain_reading_activity_retention(  # noqa: SLF001
            "https://server.example"
        )

    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_hourly_entrypoint_uses_daily_zotero_threshold_and_runs_retention() -> None:
    with (
        patch.dict(schedule_maintenance.os.environ, {}, clear=True),
        patch(
            "src.schedule_maintenance.callback_base_url",
            return_value="https://server.example",
        ),
        patch(
            "src.schedule_maintenance.post_signed_json",
            return_value=_response({"scheduled_jobs": 4}),
        ) as post,
        patch("src.schedule_maintenance._drain_reading_activity_retention") as drain,
    ):
        result = schedule_maintenance.main()

    assert result == 0
    assert post.call_args.args[0].endswith(
        "/internal/v1/schedules/zotero-sync?threshold_seconds=86400"
    )
    drain.assert_called_once_with("https://server.example")


def test_hourly_entrypoint_attempts_retention_when_zotero_schedule_fails() -> None:
    with (
        patch(
            "src.schedule_maintenance.callback_base_url",
            return_value="https://server.example",
        ),
        patch(
            "src.schedule_maintenance._schedule_due_zotero_syncs",
            side_effect=requests.HTTPError("zotero unavailable"),
        ),
        patch("src.schedule_maintenance._drain_reading_activity_retention") as drain,
        pytest.raises(RuntimeError, match="hourly_server_maintenance_failed"),
    ):
        schedule_maintenance.main()

    drain.assert_called_once_with("https://server.example")


def test_hourly_entrypoint_attempts_zotero_when_retention_fails() -> None:
    with (
        patch(
            "src.schedule_maintenance.callback_base_url",
            return_value="https://server.example",
        ),
        patch("src.schedule_maintenance._schedule_due_zotero_syncs") as zotero,
        patch(
            "src.schedule_maintenance._drain_reading_activity_retention",
            side_effect=requests.HTTPError("retention unavailable"),
        ),
        pytest.raises(RuntimeError, match="hourly_server_maintenance_failed"),
    ):
        schedule_maintenance.main()

    zotero.assert_called_once_with("https://server.example")
