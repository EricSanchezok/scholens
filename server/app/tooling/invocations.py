"""Transport-neutral persistence port for write-tool replay."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID

from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.domain import AppError, FailureKind, JsonValue
from pydantic import BaseModel


class ToolInvocationGateway(Protocol):
    def replay(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
    ) -> JsonValue | None: ...

    def complete(
        self,
        *,
        actor_id: int,
        operation_id: UUID,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None: ...


def tool_arguments_hash(arguments: BaseModel) -> str:
    """Hash validated arguments exactly as invocation replay binding does."""
    try:
        normalized = normalize_json_value(arguments)
    except JsonNormalizationError as exc:  # pragma: no cover - validated earlier
        raise AppError(
            kind=FailureKind.INVALID_ARGUMENT,
            code="tool_arguments_invalid",
            message="Tool arguments are invalid",
        ) from exc
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ToolInvocationGateway", "tool_arguments_hash"]
