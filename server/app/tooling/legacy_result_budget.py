"""Hydration preflights for deprecated full-payload MCP read tools."""

from __future__ import annotations

from app.shared.domain import AppError, FailureKind
from app.tooling.contracts import DEFAULT_TOOL_OUTPUT_BYTES

# A successful MCP result contains the structured result twice: once as
# structuredContent and once as a JSON string in the compatibility text block.
# Encoding that text block into the outer CallToolResult can at most double its
# already-serialized JSON bytes (quotes and backslashes are the worst case).
# Therefore three copies of the durable payload, plus a fixed allowance for the
# bounded result keys and one bounded resource link, is a safe upper bound.
LEGACY_CALL_TOOL_RESULT_FIXED_UTF8_BYTES = 16 * 1024
LEGACY_CALL_TOOL_RESULT_PAYLOAD_MULTIPLIER = 3


def legacy_call_tool_result_utf8_upper_bound(
    *, payload_json_utf8_upper_bound: int
) -> int:
    if payload_json_utf8_upper_bound < 0:
        raise ValueError("payload JSON upper bound must not be negative")
    return (
        LEGACY_CALL_TOOL_RESULT_PAYLOAD_MULTIPLIER * payload_json_utf8_upper_bound
        + LEGACY_CALL_TOOL_RESULT_FIXED_UTF8_BYTES
    )


def legacy_payload_json_utf8_budget(
    *, max_output_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES
) -> int:
    if max_output_bytes <= LEGACY_CALL_TOOL_RESULT_FIXED_UTF8_BYTES:
        raise ValueError("tool output budget cannot fit the fixed result envelope")
    return (
        max_output_bytes - LEGACY_CALL_TOOL_RESULT_FIXED_UTF8_BYTES
    ) // LEGACY_CALL_TOOL_RESULT_PAYLOAD_MULTIPLIER


def require_legacy_payload_budget(
    *,
    payload_json_utf8_upper_bound: int | None,
    tool: str,
    replacement_tool: str,
    max_output_bytes: int = DEFAULT_TOOL_OUTPUT_BYTES,
) -> None:
    if payload_json_utf8_upper_bound is None:
        raise RuntimeError("legacy_json_size_preflight_missing")
    result_upper_bound = legacy_call_tool_result_utf8_upper_bound(
        payload_json_utf8_upper_bound=payload_json_utf8_upper_bound
    )
    if result_upper_bound <= max_output_bytes:
        return
    raise AppError(
        code="tool_result_budget_exceeded",
        message="The tool result exceeds its safe output budget",
        kind=FailureKind.INTERNAL,
        details={
            "tool": tool,
            "max_output_bytes": max_output_bytes,
            "durable_json_utf8_upper_bound": payload_json_utf8_upper_bound,
            "call_tool_result_utf8_upper_bound": result_upper_bound,
            "replacement_tool": replacement_tool,
        },
    )


__all__ = [
    "LEGACY_CALL_TOOL_RESULT_FIXED_UTF8_BYTES",
    "LEGACY_CALL_TOOL_RESULT_PAYLOAD_MULTIPLIER",
    "legacy_call_tool_result_utf8_upper_bound",
    "legacy_payload_json_utf8_budget",
    "require_legacy_payload_budget",
]
