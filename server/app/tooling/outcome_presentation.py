"""Consistent, transport-neutral presentation of successful tool outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.shared.domain import JsonValue
from app.tooling.contracts import ToolOutcome, ToolOutcomePresentation

_COLLECTION_FIELDS = (
    "items",
    "results",
    "matches",
    "lines",
    "papers",
    "projects",
    "jobs",
    "threads",
    "comments",
    "outputs",
    "tags",
)


def outcome_presentation(outcome: ToolOutcome) -> ToolOutcomePresentation:
    """Describe a successful outcome without exposing arguments or payload data."""

    if outcome.presentation is not None:
        return outcome.presentation
    payload = outcome.payload
    if isinstance(payload, Mapping):
        changed = payload.get("changed")
        if isinstance(changed, bool):
            return ToolOutcomePresentation(
                outcome="changed" if changed else "unchanged",
                result_count=1 if changed else 0,
            )
        for field in _COLLECTION_FIELDS:
            value = payload.get(field)
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                count = len(value)
                return ToolOutcomePresentation(
                    outcome="results" if count else "empty",
                    result_count=count,
                )
    if outcome.action is not None:
        return ToolOutcomePresentation(outcome="changed", result_count=1)
    return ToolOutcomePresentation(outcome="results", result_count=1)


def presentation_payload(
    presentation: ToolOutcomePresentation,
) -> dict[str, JsonValue]:
    return {
        "outcome": presentation.outcome,
        "result_count": presentation.result_count,
    }
