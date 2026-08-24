"""Small composable helpers for lossy, explicitly bounded tool summaries."""

from __future__ import annotations

from app.shared.application.text import json_bounded_prefix


def bounded_text(value: str, *, max_bytes: int) -> tuple[str, bool]:
    bounded = json_bounded_prefix(value, max_bytes=max_bytes)
    return bounded, bounded != value


def bounded_optional_text(
    value: str | None,
    *,
    max_bytes: int,
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return bounded_text(value, max_bytes=max_bytes)


def bounded_text_list(
    values: list[str] | None,
    *,
    max_items: int,
    item_max_bytes: int,
) -> tuple[list[str] | None, bool]:
    if values is None:
        return None, False
    page = values[:max_items]
    projected: list[str] = []
    truncated = len(page) != len(values)
    for value in page:
        bounded, item_truncated = bounded_text(value, max_bytes=item_max_bytes)
        projected.append(bounded)
        truncated = truncated or item_truncated
    return projected, truncated


__all__ = ["bounded_optional_text", "bounded_text", "bounded_text_list"]
