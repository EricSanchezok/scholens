"""Size accounting for the deprecated complete Research-output projections."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.shared.domain import AppError, FailureKind


# These allowances produce a conservative payload-equivalent batch size. A
# per-item ResourceLink allowance is deliberately folded into that value before
# the shared multiplier, while the CallToolResult fixed envelope is owned by
# app.tooling.legacy_result_budget and is counted only once there.
LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES = 4 * 1024
LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES = 896
LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES = 512
LEGACY_RESEARCH_AUDIO_URL_JSON_UTF8_BYTES = 4 * 1024
LEGACY_RESEARCH_LIBRARY_WRAPPER_FIXED_JSON_UTF8_BYTES = 256
LEGACY_RESEARCH_RESOURCE_LINK_JSON_UTF8_BYTES = 512


def hostile_json_string_utf8_upper_bound(value: str | None) -> int:
    """Bound one arbitrary UTF-8 string after JSON escaping.

    A single input byte can expand to at most a six-byte ``\\u00XX`` escape.
    The quotes are included so callers do not need a per-field allowance.
    """

    return 2 if value is None else 6 * len(value.encode("utf-8")) + 2


@dataclass(frozen=True, slots=True)
class LegacyResearchListItemSize:
    item_json_utf8_upper_bound: int
    title: str | None = None
    source_title: str | None = None
    wrapped: bool = False

    def payload_json_utf8_upper_bound(self) -> int:
        if self.item_json_utf8_upper_bound < 0:
            raise ValueError("item JSON upper bound must not be negative")
        value = (
            self.item_json_utf8_upper_bound
            + LEGACY_RESEARCH_RESOURCE_LINK_JSON_UTF8_BYTES
        )
        if self.wrapped:
            value += LEGACY_RESEARCH_LIBRARY_WRAPPER_FIXED_JSON_UTF8_BYTES
            value += hostile_json_string_utf8_upper_bound(self.title)
            value += hostile_json_string_utf8_upper_bound(self.source_title)
        return value


def legacy_research_list_payload_json_utf8_upper_bound(
    items: Iterable[LegacyResearchListItemSize],
) -> int:
    """Return a batch-specific payload-equivalent bound with one fixed cost."""

    return LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES + sum(
        item.payload_json_utf8_upper_bound() for item in items
    )


def require_legacy_research_list_payload_budget(
    *,
    payload_json_utf8_upper_bound: int,
    maximum_payload_json_bytes: int,
) -> None:
    if payload_json_utf8_upper_bound <= maximum_payload_json_bytes:
        return
    raise AppError(
        code="tool_result_budget_exceeded",
        message="The tool result exceeds its safe output budget",
        kind=FailureKind.INTERNAL,
        details={
            "tool": "list_research_outputs",
            "durable_json_utf8_upper_bound": payload_json_utf8_upper_bound,
            "replacement_tool": "list_research_output_summaries",
        },
    )


__all__ = [
    "LEGACY_RESEARCH_AUDIO_URL_JSON_UTF8_BYTES",
    "LEGACY_RESEARCH_COMMENT_FIXED_JSON_UTF8_BYTES",
    "LEGACY_RESEARCH_ITEM_FIXED_JSON_UTF8_BYTES",
    "LEGACY_RESEARCH_LIST_FIXED_JSON_UTF8_BYTES",
    "LegacyResearchListItemSize",
    "hostile_json_string_utf8_upper_bound",
    "legacy_research_list_payload_json_utf8_upper_bound",
    "require_legacy_research_list_payload_budget",
]
