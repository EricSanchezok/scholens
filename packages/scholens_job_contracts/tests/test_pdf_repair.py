from __future__ import annotations

from typing import Any

import pytest

from scholens_job_contracts import (
    PDF_TEXT_REPAIR_MAX_ATTEMPTS,
    PDF_TEXT_REPAIR_TASK_NAME,
    PDFTextRepairTaskRequest,
)

_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_DOCUMENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_SOURCE_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _request(**overrides: object) -> PDFTextRepairTaskRequest:
    values: dict[str, Any] = {
        "job_id": _JOB_ID,
        "document_id": _DOCUMENT_ID,
        "s3_key": f"documents/{'d' * 64}/source.pdf",
        "callback_url": "https://server.internal/internal/v1/jobs/callback",
        "claim_url": "https://server.internal/internal/v1/jobs/claim",
        "progress_url": "https://server.internal/internal/v1/jobs/progress",
        "mineru_credential_url": (
            "https://server.internal/internal/v1/jobs/mineru-credential"
        ),
        "repair_revision": "unicode-replacement-v1",
        "source_job_id": _SOURCE_JOB_ID,
        "source_content_digest": "e" * 64,
        "repair_attempt": 1,
    }
    values.update(overrides)
    return PDFTextRepairTaskRequest(**values)


def test_pdf_text_repair_contract_has_exact_serialized_shape() -> None:
    request = _request()

    assert PDF_TEXT_REPAIR_TASK_NAME == "repair_pdf_text"
    assert PDF_TEXT_REPAIR_MAX_ATTEMPTS == 3
    assert request.as_task_kwargs() == {
        "job_id": _JOB_ID,
        "document_id": _DOCUMENT_ID,
        "s3_key": f"documents/{'d' * 64}/source.pdf",
        "callback_url": "https://server.internal/internal/v1/jobs/callback",
        "claim_url": "https://server.internal/internal/v1/jobs/claim",
        "progress_url": "https://server.internal/internal/v1/jobs/progress",
        "mineru_credential_url": (
            "https://server.internal/internal/v1/jobs/mineru-credential"
        ),
        "repair_revision": "unicode-replacement-v1",
        "source_job_id": _SOURCE_JOB_ID,
        "source_content_digest": "e" * 64,
        "repair_attempt": 1,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_id", "not-a-uuid"),
        ("document_id", "not-a-uuid"),
        ("s3_key", "documents/not-canonical/source.pdf"),
        ("s3_key", None),
        ("callback_url", ""),
        ("repair_revision", "INVALID"),
        ("source_job_id", "not-a-uuid"),
        ("source_content_digest", "A" * 64),
        ("repair_attempt", 0),
        ("repair_attempt", 4),
        ("repair_attempt", True),
        ("repair_attempt", "1"),
    ],
)
def test_pdf_text_repair_contract_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        _request(**{field: value})
