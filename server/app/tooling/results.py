"""Strict serialization for tool outcomes and persisted invocation receipts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling.contracts import (
    ToolOutcome,
    ToolResourceLink,
    ToolSourceCandidate,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _PersistedToolResourceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str
    name: str
    description: str | None = None
    mime_type: str = "application/json"


class _PersistedToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: JsonValue
    sources: tuple[ToolSourceCandidate, ...] = ()
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    resource_links: list[_PersistedToolResourceLink] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SerializedToolSuccess:
    """Strict, normalized representation of one successful MCP tool result."""

    outcome: ToolOutcome
    structured_content: dict[str, JsonValue]
    text_content: str
    call_tool_result_utf8_bytes: int


def _normalized_persisted_outcome(
    outcome: ToolOutcome,
) -> tuple[_PersistedToolOutcome, dict[str, JsonValue]]:
    try:
        normalized = normalize_json_value(
            {
                "payload": outcome.payload,
                "sources": [asdict(source) for source in outcome.sources],
                "artifacts": outcome.artifacts,
                "action": outcome.action,
                "resource_links": [asdict(link) for link in outcome.resource_links],
            }
        )
        if not isinstance(normalized, dict):  # pragma: no cover - model invariant
            raise JsonNormalizationError("tool outcome must be a JSON object")
        persisted = _PersistedToolOutcome.model_validate(normalized)
        canonical = normalize_json_value(persisted.model_dump(mode="json"))
        if not isinstance(canonical, dict):  # pragma: no cover - model invariant
            raise JsonNormalizationError("tool outcome must be a JSON object")
    except JsonNormalizationError:
        raise
    except Exception as exc:
        raise JsonNormalizationError(
            "tool outcome cannot be represented as strict JSON"
        ) from exc
    return persisted, canonical


def _outcome_from_persisted(persisted: _PersistedToolOutcome) -> ToolOutcome:
    return ToolOutcome(
        payload=persisted.payload,
        sources=persisted.sources,
        artifacts=persisted.artifacts,
        action=persisted.action,
        resource_links=tuple(
            ToolResourceLink(
                uri=link.uri,
                name=link.name,
                description=link.description,
                mime_type=link.mime_type,
            )
            for link in persisted.resource_links
        ),
    )


def persisted_tool_outcome(outcome: ToolOutcome) -> JsonValue:
    """Return the canonical strict-JSON receipt stored for a successful tool."""
    try:
        _, normalized = _normalized_persisted_outcome(outcome)
    except JsonNormalizationError as exc:  # pragma: no cover - finalized invariant
        raise AppError(
            kind=FailureKind.INTERNAL,
            code="tool_result_invalid",
            message="The tool produced an invalid result",
        ) from exc
    return normalized


def serialize_tool_success(outcome: ToolOutcome) -> SerializedToolSuccess:
    """Render and measure the complete MCP ``CallToolResult`` result object.

    Measurement includes the compatibility text block, structured content,
    and standalone resource links. The surrounding JSON-RPC request envelope
    is deliberately outside the per-tool result budget.
    """
    persisted, persisted_value = _normalized_persisted_outcome(outcome)
    normalized_outcome = _outcome_from_persisted(persisted)
    structured: dict[str, JsonValue] = {
        "result": persisted_value["payload"],
        "sources": persisted_value["sources"],
        "artifacts": persisted_value["artifacts"],
        "action": persisted_value["action"],
        "resource_links": persisted_value["resource_links"],
    }
    text_content = json.dumps(
        structured,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    content: list[JsonValue] = [{"type": "text", "text": text_content}]
    for link in normalized_outcome.resource_links:
        resource_block: dict[str, JsonValue] = {
            "type": "resource_link",
            "uri": link.uri,
            "name": link.name,
            "mimeType": link.mime_type,
        }
        if link.description is not None:
            resource_block["description"] = link.description
        content.append(resource_block)
    call_tool_result: dict[str, JsonValue] = {
        "content": content,
        "structuredContent": structured,
        "isError": False,
    }
    encoded = json.dumps(
        call_tool_result,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return SerializedToolSuccess(
        outcome=normalized_outcome,
        structured_content=structured,
        text_content=text_content,
        call_tool_result_utf8_bytes=len(encoded),
    )


def restore_tool_outcome(value: JsonValue) -> ToolOutcome:
    """Restore and validate one canonical tool invocation receipt."""
    try:
        normalized = normalize_json_value(value)
        persisted = _PersistedToolOutcome.model_validate(normalized)
    except (JsonNormalizationError, ValidationError) as exc:
        raise AppError(
            kind=FailureKind.DEPENDENCY_FAILURE,
            code="tool_invocation_result_invalid",
            message="Stored tool invocation result is invalid",
        ) from exc
    return _outcome_from_persisted(persisted)


__all__ = [
    "SerializedToolSuccess",
    "persisted_tool_outcome",
    "restore_tool_outcome",
    "serialize_tool_success",
]
