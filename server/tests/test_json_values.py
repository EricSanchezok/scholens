from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
import json
from uuid import UUID

import pytest
from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.application.text import json_bounded_prefix
from pydantic import BaseModel


class ExampleKind(StrEnum):
    PRIMARY = "primary"


class NestedValue(BaseModel):
    id: UUID
    created_at: datetime
    kind: ExampleKind


def test_normalize_json_value_recursively_serializes_supported_typed_values() -> None:
    identifier = UUID("11111111-1111-1111-1111-111111111111")
    created_at = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)

    result = normalize_json_value(
        {
            "model": NestedValue(
                id=identifier,
                created_at=created_at,
                kind=ExampleKind.PRIMARY,
            ),
            "typed": (
                identifier,
                created_at,
                date(2026, 8, 24),
                time(9, 30),
                ExampleKind.PRIMARY,
            ),
            "unicode": "中文 café 🔬",
        }
    )

    assert result == {
        "model": {
            "id": str(identifier),
            "created_at": "2026-08-24T09:30:00Z",
            "kind": "primary",
        },
        "typed": [
            str(identifier),
            "2026-08-24T09:30:00Z",
            "2026-08-24",
            "09:30:00",
            "primary",
        ],
        "unicode": "中文 café 🔬",
    }


@pytest.mark.parametrize(
    "value",
    [
        {"values": {"unordered"}},
        {"binary": b"private"},
        {1: "non-string key"},
        {"number": float("nan")},
        {"number": float("inf")},
        {"arbitrary": object()},
        {"value": "\ud800"},
        {"\udfff": "invalid key"},
    ],
)
def test_normalize_json_value_rejects_non_json_or_ambiguous_values(
    value: object,
) -> None:
    with pytest.raises(JsonNormalizationError):
        normalize_json_value(value)


def test_normalize_json_value_rejects_reference_cycles_without_value_repr() -> None:
    value: dict[str, object] = {}
    value["self"] = value

    with pytest.raises(JsonNormalizationError) as exc_info:
        normalize_json_value(value)

    assert "reference cycle" in str(exc_info.value)
    assert "{'self':" not in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        'plain "quoted" text',
        "control\x00\b\t\ncharacters",
        "中文 café 🔬",
    ],
)
def test_json_bounded_prefix_is_the_longest_prefix_within_each_budget(
    value: str,
) -> None:
    full_size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    for budget in range(2, full_size + 2):
        prefix = json_bounded_prefix(value, max_bytes=budget)

        assert value.startswith(prefix)
        assert len(json.dumps(prefix, ensure_ascii=False).encode("utf-8")) <= budget
        if len(prefix) < len(value):
            next_prefix = value[: len(prefix) + 1]
            assert (
                len(json.dumps(next_prefix, ensure_ascii=False).encode("utf-8"))
                > budget
            )
