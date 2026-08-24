from __future__ import annotations

import inspect
from typing import Any

import pytest

from src.tasks import repair_pdf_text

_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _kwargs() -> dict[str, Any]:
    return {
        "job_id": _JOB_ID,
        "document_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "s3_key": f"documents/{'d' * 64}/source.pdf",
        "callback_url": "https://server.internal/internal/v1/jobs/callback",
        "claim_url": "https://server.internal/internal/v1/jobs/claim",
        "progress_url": "https://server.internal/internal/v1/jobs/progress",
        "mineru_credential_url": (
            "https://server.internal/internal/v1/jobs/mineru-credential"
        ),
        "repair_revision": "unicode-replacement-v1",
        "source_job_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "source_content_digest": "e" * 64,
        "repair_attempt": 1,
    }


def test_repair_task_exposes_exact_consumer_first_kwargs() -> None:
    assert tuple(inspect.signature(repair_pdf_text.run).parameters) == tuple(_kwargs())


def test_repair_task_reuses_pdf_workflow_with_metadata_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def process(*args: object, **kwargs: object) -> dict[str, Any]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"task_id": _JOB_ID, "status": "completed"}

    monkeypatch.setattr("src.tasks._process_pdf_task", process)
    repair_pdf_text.push_request(id=_JOB_ID)
    try:
        result = repair_pdf_text.run(**_kwargs())
    finally:
        repair_pdf_text.pop_request()

    assert result == {"task_id": _JOB_ID, "status": "completed"}
    assert captured["args"][1:] == (
        f"documents/{'d' * 64}/source.pdf",
        "https://server.internal/internal/v1/jobs/callback",
        "https://server.internal/internal/v1/jobs/progress",
        "https://server.internal/internal/v1/jobs/claim",
        "https://server.internal/internal/v1/jobs/mineru-credential",
    )
    assert captured["kwargs"] == {
        "skip_metadata_extraction": True,
        "repair_revision": "unicode-replacement-v1",
    }


def test_repair_task_rejects_celery_job_id_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def process(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("src.tasks._process_pdf_task", process)
    repair_pdf_text.push_request(id="dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    try:
        with pytest.raises(ValueError, match="pdf_text_repair_job_id_mismatch"):
            repair_pdf_text.run(**_kwargs())
    finally:
        repair_pdf_text.pop_request()

    assert not called
