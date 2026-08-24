"""Bounds shared by the MCP annotation-thread summary projection."""

from __future__ import annotations

from app.shared.application.text import json_bounded_prefix

ANNOTATION_SUMMARY_MAX_PAGE_ITEMS = 50
ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES = 128
ANNOTATION_SUMMARY_QUOTE_JSON_BYTES = 256


def bounded_annotation_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    return json_bounded_prefix(
        value,
        max_bytes=ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES,
    )


def bounded_annotation_quote(value: str) -> str:
    return json_bounded_prefix(
        value,
        max_bytes=ANNOTATION_SUMMARY_QUOTE_JSON_BYTES,
    )


__all__ = [
    "ANNOTATION_SUMMARY_DISPLAY_NAME_JSON_BYTES",
    "ANNOTATION_SUMMARY_MAX_PAGE_ITEMS",
    "ANNOTATION_SUMMARY_QUOTE_JSON_BYTES",
    "bounded_annotation_display_name",
    "bounded_annotation_quote",
]
