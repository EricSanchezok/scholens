from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from src.tasks import (
    JOB_PROGRESS_TIMEOUT_SECONDS,
    JobCancelled,
    ProgressReporter,
    _MinerUCredentialSession,
    _fetch_mineru_credential,
    _pdf_failure_code,
)


def _response(*, claimed: bool = True) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"claimed": claimed}
    return response


def test_job_scoped_credential_never_enters_repr_or_callback_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "credential": "private-mineru-token",
        "credential_revision": "revision-1",
    }
    monkeypatch.setattr(
        "src.tasks.post_signed_json",
        MagicMock(return_value=response),
    )

    credential = _fetch_mineru_credential(
        "https://server.example/internal/jobs/job-1/credential"
    )
    session = _MinerUCredentialSession("https://server.example/credential")
    session.credential = credential
    session.record(credential.revision, "verified", None)

    assert "private-mineru-token" not in repr(credential)
    assert "private-mineru-token" not in repr(session)
    assert "private-mineru-token" not in str(session.events())
    assert session.events() == [
        {
            "provider": "mineru",
            "credential_revision": "revision-1",
            "outcome": "verified",
            "error_code": None,
        }
    ]


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (None, "paper_ingestion_downloading_failed"),
        ("downloading", "paper_ingestion_downloading_failed"),
        ("parsing", "paper_ingestion_parsing_failed"),
        ("extracting_metadata", "paper_ingestion_metadata_failed"),
        ("indexing", "paper_ingestion_indexing_failed"),
        ("finalizing", "paper_ingestion_finalizing_failed"),
        ("unexpected", "paper_ingestion_parsing_failed"),
    ],
)
def test_pdf_failure_code_preserves_the_failed_lifecycle_stage(
    stage: str | None,
    expected: str,
) -> None:
    assert _pdf_failure_code(stage) == expected


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
