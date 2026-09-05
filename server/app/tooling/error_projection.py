"""Shared, actionable Agent and MCP recovery guidance for tool failures."""

from __future__ import annotations

from app.shared.domain import AppError, FailureKind, JsonValue


def tool_error_remediation(
    *,
    kind: FailureKind,
    code: str,
    replacement_tool: str | None = None,
) -> str:
    if code == "tool_arguments_invalid":
        return (
            "Correct the named arguments using this tool's input schema, then call "
            "the same tool once more. Do not guess UUIDs or opaque cursors."
        )
    if code.endswith("_cursor_invalid") or code.endswith("_cursor_expired"):
        return (
            "Reuse the exact opaque cursor from the immediately preceding response "
            "with unchanged filters, or omit the cursor and restart from a known page."
        )
    if replacement_tool is not None:
        return (
            f"Do not retry the same unbounded request. Use {replacement_tool} and "
            "continue its returned cursor until the complete result is read."
        )
    if code == "tool_result_budget_exceeded":
        return (
            "Reduce the requested limit or filters, or use the documented bounded "
            "page tool and continue only with its returned cursor."
        )
    if code == "mcp_request_too_large":
        return (
            "Send one request within the advertised body limit. Use bounded reads "
            "instead of embedding stored paper content in tool arguments."
        )
    if code in {"confirmation_required", "confirmation_stale"}:
        return (
            "Show the impact preview to the user, then call the same tool with "
            "unchanged business arguments and the returned confirmation token."
        )
    if kind is FailureKind.PERMISSION_DENIED:
        return (
            "Do not retry unchanged. Request the required workspace permission or "
            "choose a resource visible to the current caller."
        )
    if kind is FailureKind.NOT_FOUND:
        return (
            "Verify the immutable UUID with the corresponding list or search tool; "
            "the resource may have been deleted or may not be visible."
        )
    if kind is FailureKind.CONFLICT:
        return (
            "Refresh the resource, preserve the idempotency key for the same logical "
            "action, and retry only after adapting to its current state."
        )
    if kind is FailureKind.PAYLOAD_TOO_LARGE:
        return (
            "Reduce the request to its advertised limit. Use bounded pages for reads "
            "or begin a new upload session with a smaller PDF."
        )
    if kind is FailureKind.RATE_LIMITED:
        return "Wait before retrying and reuse the same idempotency key for the same action."
    if kind in {FailureKind.DEPENDENCY_FAILURE, FailureKind.UNAVAILABLE}:
        return (
            "Retry after a short delay with the same idempotency key. If it persists, "
            "report the diagnostic ID instead of retrying repeatedly."
        )
    if kind is FailureKind.UNAUTHENTICATED:
        return (
            "Reconnect with an active Scholens credential; never place credentials "
            "in tool arguments."
        )
    return "Review the error code, correct the request, and avoid blind retries."


def project_tool_error(error: AppError) -> dict[str, JsonValue]:
    replacement = None
    if error.details is not None:
        candidate = error.details.get("replacement_tool")
        if isinstance(candidate, str):
            replacement = candidate
    projected: dict[str, JsonValue] = {
        "code": error.code,
        "kind": error.kind.value,
        "retryable": error.retryable,
        "message": error.message,
        "remediation": tool_error_remediation(
            kind=error.kind,
            code=error.code,
            replacement_tool=replacement,
        ),
    }
    if replacement is not None:
        projected["replacement_tool"] = replacement
    return projected
