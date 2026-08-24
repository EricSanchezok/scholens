from __future__ import annotations

import pytest
from scholens_job_contracts import (
    MAX_JOBS_CALLBACK_BODY_BYTES,
    MAX_PDF_CALLBACK_RAW_CONTENT_BYTES,
    callback_json_bytes,
    require_callback_body_size,
    require_pdf_callback_content_size,
)


def test_callback_body_contract_uses_exact_wire_encoding() -> None:
    payload = {"control": "\x00", "unicode": "论文"}

    assert callback_json_bytes(payload) == (
        b'{"control":"\\u0000","unicode":"\xe8\xae\xba\xe6\x96\x87"}'
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_callback_body_contract_rejects_non_finite_json_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        callback_json_bytes({"value": value})


def test_callback_body_contract_rejects_only_above_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholens_job_contracts import callbacks

    monkeypatch.setattr(callbacks, "MAX_JOBS_CALLBACK_BODY_BYTES", 8)
    require_callback_body_size(b"x" * 8)

    with pytest.raises(ValueError, match="jobs_callback_too_large"):
        require_callback_body_size(b"x" * 9)


def test_pdf_content_contract_uses_utf8_and_json_byte_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholens_job_contracts import callbacks

    monkeypatch.setattr(callbacks, "MAX_PDF_CALLBACK_RAW_CONTENT_BYTES", 8)
    monkeypatch.setattr(callbacks, "MAX_PDF_CALLBACK_PAGE_OFFSET_MAP_BYTES", 11)
    require_pdf_callback_content_size(
        raw_content="x" * 8,
        page_offset_map={1: [0, 1]},
    )

    with pytest.raises(ValueError, match="raw_content_too_large"):
        require_pdf_callback_content_size(
            raw_content="论文论",
            page_offset_map=None,
        )

    with pytest.raises(ValueError, match="page_offset_map_too_large"):
        require_pdf_callback_content_size(
            raw_content=None,
            page_offset_map={1: [0, 1], 2: [1, 2]},
        )


@pytest.mark.parametrize(
    "page_offset_map",
    [
        {0: [0, 1]},
        {1: [0]},
        {1: [-1, 1]},
        {1: [2, 1]},
        {1: [0, 4]},
        {1: [0, 2], 2: [1, 3]},
        {1: [False, 1]},
    ],
)
def test_pdf_content_contract_rejects_invalid_page_offsets(
    page_offset_map: dict[int, list[int]],
) -> None:
    with pytest.raises(ValueError, match="page_offset_map_invalid"):
        require_pdf_callback_content_size(
            raw_content="abc",
            page_offset_map=page_offset_map,
        )


def test_maximum_plain_text_pdf_result_fits_aggregate_callback_budget() -> None:
    payload = {
        "task_id": "00000000-0000-0000-0000-000000000000",
        "status": "completed",
        "result": {
            "success": True,
            "job_id": "00000000-0000-0000-0000-000000000000",
            "raw_content": "x" * MAX_PDF_CALLBACK_RAW_CONTENT_BYTES,
            "page_offset_map": {1: [0, MAX_PDF_CALLBACK_RAW_CONTENT_BYTES]},
            "parser_backend": "pymupdf4llm",
            "parser_quality": "full",
            "parser_version": "test",
        },
        "error": None,
        "usage_events": [],
        "integration_events": [],
    }
    body = callback_json_bytes(payload)

    require_callback_body_size(body)
    assert len(body) < MAX_JOBS_CALLBACK_BODY_BYTES


def test_hostile_control_text_is_rejected_by_aggregate_callback_budget() -> None:
    body = callback_json_bytes(
        {"raw_content": "\x00" * (MAX_JOBS_CALLBACK_BODY_BYTES // 6 + 1)}
    )

    with pytest.raises(ValueError, match="jobs_callback_too_large"):
        require_callback_body_size(body)
