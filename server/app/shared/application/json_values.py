"""Strict normalization at boundaries that require JSON-native values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, time
from enum import Enum
from typing import cast
from uuid import UUID

from app.shared.domain import JsonValue
from pydantic import BaseModel, TypeAdapter, ValidationError

_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)
_DATE: TypeAdapter[date] = TypeAdapter(date)
_TIME: TypeAdapter[time] = TypeAdapter(time)
_MAX_JSON_DEPTH = 100
_UNICODE_VALIDATION_CHUNK_CHARACTERS = 64 * 1024


class JsonNormalizationError(TypeError):
    """The supplied value cannot be represented as strict JSON."""


def require_valid_json_string(value: str, *, path: str = "$") -> str:
    """Reject lone surrogates with a fixed-size transient UTF-8 allocation."""

    try:
        for start in range(0, len(value), _UNICODE_VALIDATION_CHUNK_CHARACTERS):
            value[start : start + _UNICODE_VALIDATION_CHUNK_CHARACTERS].encode("utf-8")
    except UnicodeEncodeError as exc:
        raise JsonNormalizationError(f"{path} contains invalid Unicode") from exc
    return value


def _normalize_json_value(
    value: object,
    *,
    path: str,
    depth: int,
    active_containers: set[int],
) -> JsonValue:
    if depth > _MAX_JSON_DEPTH:
        raise JsonNormalizationError(f"{path} exceeds the maximum JSON nesting depth")

    if isinstance(value, BaseModel):
        try:
            dumped = value.model_dump(mode="json")
        except Exception as exc:
            raise JsonNormalizationError(
                f"{path} contains a model that cannot be serialized as JSON"
            ) from exc
        return _normalize_json_value(
            dumped,
            path=path,
            depth=depth + 1,
            active_containers=active_containers,
        )

    if isinstance(value, Enum):
        return _normalize_json_value(
            value.value,
            path=path,
            depth=depth + 1,
            active_containers=active_containers,
        )
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return cast(str, _DATETIME.dump_python(value, mode="json"))
    if isinstance(value, date):
        return cast(str, _DATE.dump_python(value, mode="json"))
    if isinstance(value, time):
        return cast(str, _TIME.dump_python(value, mode="json"))
    if isinstance(value, str):
        return require_valid_json_string(value, path=path)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonNormalizationError(f"{path} contains a non-finite number")
        return value

    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_containers:
            raise JsonNormalizationError(f"{path} contains a reference cycle")
        active_containers.add(container_id)
        try:
            normalized: dict[str, JsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise JsonNormalizationError(
                        f"{path} contains a non-string object key"
                    )
                require_valid_json_string(key, path=f"{path} object key")
                normalized[key] = _normalize_json_value(
                    item,
                    path=f"{path}.*",
                    depth=depth + 1,
                    active_containers=active_containers,
                )
            return normalized
        finally:
            active_containers.remove(container_id)

    if isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in active_containers:
            raise JsonNormalizationError(f"{path} contains a reference cycle")
        active_containers.add(container_id)
        try:
            return [
                _normalize_json_value(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    active_containers=active_containers,
                )
                for index, item in enumerate(value)
            ]
        finally:
            active_containers.remove(container_id)

    raise JsonNormalizationError(
        f"{path} contains unsupported type {type(value).__name__}"
    )


def normalize_json_value(value: object) -> JsonValue:
    """Recursively convert supported typed values to one strict JSON value.

    This function is deliberately not a public-data projection or redaction
    boundary. Callers must select safe fields before normalization.
    """

    normalized = _normalize_json_value(
        value,
        path="$",
        depth=0,
        active_containers=set(),
    )
    try:
        return _JSON_VALUE.validate_python(normalized)
    except ValidationError as exc:  # pragma: no cover - defensive invariant
        raise JsonNormalizationError(
            "The normalized value does not satisfy the JSON value contract"
        ) from exc


__all__ = [
    "JsonNormalizationError",
    "normalize_json_value",
    "require_valid_json_string",
]
