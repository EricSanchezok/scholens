"""Service-neutral size contract for Jobs -> Server HTTP callbacks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

MAX_JOBS_CALLBACK_BODY_BYTES = 64 * 1024 * 1024
# Repair candidates may be 125% of the 32 MiB canonical source ceiling. Keep
# the transport field large enough for that accepted quality-contract range.
MAX_PDF_CALLBACK_RAW_CONTENT_BYTES = 40 * 1024 * 1024
MAX_PDF_CALLBACK_PAGE_OFFSET_MAP_BYTES = 2 * 1024 * 1024


def callback_json_bytes(payload: object) -> bytes:
    """Encode callback JSON exactly as the Jobs transport signs and sends it."""

    return json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def require_callback_body_size(body: bytes) -> None:
    """Reject a callback body that Server cannot accept."""

    if len(body) > MAX_JOBS_CALLBACK_BODY_BYTES:
        raise ValueError(
            "jobs_callback_too_large: "
            f"{len(body)} bytes exceeds {MAX_JOBS_CALLBACK_BODY_BYTES}"
        )


def require_pdf_callback_content_size(
    *,
    raw_content: str | None,
    page_offset_map: Mapping[Any, object] | None,
) -> None:
    """Bound the two parser-controlled fields carried by a PDF callback."""

    if (
        raw_content is not None
        and len(raw_content.encode("utf-8")) > MAX_PDF_CALLBACK_RAW_CONTENT_BYTES
    ):
        raise ValueError(
            "pdf_callback_raw_content_too_large: "
            f"content exceeds {MAX_PDF_CALLBACK_RAW_CONTENT_BYTES} UTF-8 bytes"
        )
    if page_offset_map is not None:
        normalized_bounds: list[tuple[int, int, int]] = []
        for raw_page_number, raw_bounds in page_offset_map.items():
            page_number = (
                int(raw_page_number)
                if isinstance(raw_page_number, str) and raw_page_number.isdecimal()
                else raw_page_number
            )
            if (
                isinstance(page_number, bool)
                or not isinstance(page_number, int)
                or page_number <= 0
                or not isinstance(raw_bounds, Sequence)
                or isinstance(raw_bounds, (str, bytes, bytearray))
                or len(raw_bounds) != 2
            ):
                raise ValueError("pdf_callback_page_offset_map_invalid")
            start, end = raw_bounds
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
            ):
                raise ValueError("pdf_callback_page_offset_map_invalid")
            normalized_bounds.append((page_number, start, end))

        previous_end = 0
        content_length = len(raw_content) if raw_content is not None else None
        for _page_number, start, end in sorted(normalized_bounds):
            if (
                start < previous_end
                or start < 0
                or end < start
                or (content_length is not None and end > content_length)
            ):
                raise ValueError("pdf_callback_page_offset_map_invalid")
            previous_end = end
        encoded = callback_json_bytes(page_offset_map)
        if len(encoded) > MAX_PDF_CALLBACK_PAGE_OFFSET_MAP_BYTES:
            raise ValueError(
                "pdf_callback_page_offset_map_too_large: "
                "page map exceeds "
                f"{MAX_PDF_CALLBACK_PAGE_OFFSET_MAP_BYTES} JSON bytes"
            )


__all__ = [
    "MAX_JOBS_CALLBACK_BODY_BYTES",
    "MAX_PDF_CALLBACK_PAGE_OFFSET_MAP_BYTES",
    "MAX_PDF_CALLBACK_RAW_CONTENT_BYTES",
    "callback_json_bytes",
    "require_callback_body_size",
    "require_pdf_callback_content_size",
]
