from __future__ import annotations

import json

import pytest

from app.shared.domain import AppError
from app.tooling.contracts import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    ToolOutcome,
    ToolResourceLink,
)
from app.tooling.legacy_result_budget import (
    legacy_call_tool_result_utf8_upper_bound,
    legacy_payload_json_utf8_budget,
    require_legacy_payload_budget,
)
from app.tooling.results import serialize_tool_success


def test_legacy_envelope_bound_covers_hostile_json_escaping() -> None:
    payload = {"value": '\x00\\"' * 6_000}
    payload_bytes = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    )
    outcome = ToolOutcome(
        payload=payload,
        resource_links=(
            ToolResourceLink(
                uri="scholens://papers/00000000-0000-0000-0000-000000000000",
                name="paper",
                description="Canonical paper metadata.",
            ),
        ),
    )

    actual = serialize_tool_success(outcome).call_tool_result_utf8_bytes
    upper_bound = legacy_call_tool_result_utf8_upper_bound(
        payload_json_utf8_upper_bound=payload_bytes
    )

    assert payload_bytes <= legacy_payload_json_utf8_budget()
    assert actual <= upper_bound <= DEFAULT_TOOL_OUTPUT_BYTES


def test_legacy_envelope_preflight_rejects_the_old_half_budget_threshold() -> None:
    with pytest.raises(AppError) as raised:
        require_legacy_payload_budget(
            payload_json_utf8_upper_bound=98_300,
            tool="get_paper",
            replacement_tool="get_paper_page",
        )

    assert raised.value.code == "tool_result_budget_exceeded"
    assert raised.value.details is not None
    assert (
        raised.value.details["call_tool_result_utf8_upper_bound"]
        > DEFAULT_TOOL_OUTPUT_BYTES
    )


def test_legacy_envelope_estimator_rejects_negative_payload_bounds() -> None:
    with pytest.raises(ValueError, match="negative"):
        legacy_call_tool_result_utf8_upper_bound(
            payload_json_utf8_upper_bound=-1,
        )
