from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from src.tasks import (
    JOB_PROGRESS_TIMEOUT_SECONDS,
    JobCancelled,
    ProgressReporter,
)


def _response(*, claimed: bool = True) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"claimed": claimed}
    return response


def test_progress_reporter_normalizes_stage_and_uses_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(update_state=MagicMock())
    post = MagicMock(return_value=_response())
    monkeypatch.setattr("src.tasks.post_signed_json", post)
    reporter = ProgressReporter(
        task=task,
        task_id="job-1",
        progress_url="https://server.example/jobs/job-1/progress",
    )

    reporter.update("Extracting paper metadata")

    task.update_state.assert_called_once_with(
        state="PROGRESS",
        meta={"status": "Extracting paper metadata"},
    )
    post.assert_called_once_with(
        "https://server.example/jobs/job-1/progress",
        {"progress_code": "extracting_metadata"},
        timeout=JOB_PROGRESS_TIMEOUT_SECONDS,
    )


def test_progress_reporter_prioritizes_terminal_stage_over_processing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(update_state=MagicMock())
    post = MagicMock(return_value=_response())
    monkeypatch.setattr("src.tasks.post_signed_json", post)
    reporter = ProgressReporter(
        task=task,
        task_id="job-finalizing",
        progress_url="https://server.example/jobs/job-finalizing/progress",
    )

    reporter.update("Processing PDF file")
    reporter.update("PDF processing complete!")

    assert post.call_args_list[-1].args[1] == {"progress_code": "finalizing"}


def test_progress_reporter_stops_at_next_boundary_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(update_state=MagicMock())
    monkeypatch.setattr(
        "src.tasks.post_signed_json",
        MagicMock(return_value=_response(claimed=False)),
    )
    reporter = ProgressReporter(
        task=task,
        task_id="job-2",
        progress_url="https://server.example/jobs/job-2/progress",
    )

    with pytest.raises(JobCancelled, match="paper_ingestion_cancelled"):
        reporter.update("Processing PDF file")


def test_progress_delivery_outage_does_not_fail_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(update_state=MagicMock())
    monkeypatch.setattr(
        "src.tasks.post_signed_json",
        MagicMock(side_effect=requests.Timeout("offline")),
    )
    reporter = ProgressReporter(
        task=task,
        task_id="job-3",
        progress_url="https://server.example/jobs/job-3/progress",
    )

    reporter.update("Downloading PDF from S3")
    reporter.check_cancelled()
