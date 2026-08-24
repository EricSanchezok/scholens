"""Bounded MCP projections for citation metadata and provider diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time
from enum import Enum
from itertools import islice
from typing import cast
from uuid import UUID

from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationResult,
    CitationStep,
)
from app.shared.application.json_values import (
    JsonNormalizationError,
    normalize_json_value,
)
from app.shared.application.text import json_bounded_prefix
from app.shared.domain import JsonValue
from app.tooling import workspace_contracts as wc
from app.tooling.bounded_projection import (
    bounded_optional_text as _optional_text,
    bounded_text as _text,
)
from app.tooling.contracts import ToolOutcome
from pydantic import BaseModel, Field

CITATION_TITLE_JSON_BYTES = 2_048
CITATION_FIELD_JSON_BYTES = 1_024
CITATION_AUTHOR_JSON_BYTES = 256
CITATION_STEP_DETAIL_JSON_BYTES = 512
CITATION_DIAGNOSTIC_STRING_JSON_BYTES = 96
CITATION_DIAGNOSTIC_KEY_JSON_BYTES = 96
CITATION_FILLED_FIELD_JSON_BYTES = 512
CITATION_DIAGNOSTIC_NESTED_ITEMS = 3
CITATION_DIAGNOSTIC_MAX_DEPTH = 1

CITATION_READ_GUIDANCE = (
    "Citation fields are bounded previews when content_truncated is true. Use "
    "get_paper_page and continue with next_cursor for lossless stored metadata; "
    "call resolve_paper_citation only when required fields are missing."
)
CITATION_RESOLUTION_GUIDANCE = (
    "Citation fields and provider steps are bounded diagnostics when "
    "content_truncated is true. No duplicate citation artifact is emitted. Use "
    "resource_uri or get_paper_page for lossless stored metadata; provider steps "
    "are diagnostic and are not a durable metadata record."
)


class _CitationReadEnvelope(BaseModel):
    document_id: UUID
    preferred_style: str
    data: CitationData
    missing_fields: list[str] = Field(default_factory=list)
    complete: bool
    content_truncated: bool = False
    guidance: str = ""


def _text_list(
    values: Sequence[str],
    *,
    max_items: int,
    item_max_bytes: int,
) -> tuple[list[str], bool]:
    projected: list[str] = []
    truncated = len(values) > max_items
    for value in values[:max_items]:
        bounded, item_truncated = _text(value, max_bytes=item_max_bytes)
        projected.append(bounded)
        truncated = truncated or item_truncated
    return projected, truncated


def _citation_data(
    value: CitationData,
    *,
    document_id: str,
) -> tuple[wc.CitationDataOutput, bool]:
    title, title_truncated = _optional_text(
        value.title,
        max_bytes=CITATION_TITLE_JSON_BYTES,
    )
    authors, authors_truncated = _text_list(
        value.authors,
        max_items=wc.CITATION_MAX_AUTHORS,
        item_max_bytes=CITATION_AUTHOR_JSON_BYTES,
    )
    publish_date, publish_date_truncated = _optional_text(
        value.publish_date,
        max_bytes=CITATION_FIELD_JSON_BYTES,
    )
    journal, journal_truncated = _optional_text(
        value.journal,
        max_bytes=CITATION_FIELD_JSON_BYTES,
    )
    publisher, publisher_truncated = _optional_text(
        value.publisher,
        max_bytes=CITATION_FIELD_JSON_BYTES,
    )
    doi, doi_truncated = _optional_text(
        value.doi,
        max_bytes=CITATION_FIELD_JSON_BYTES,
    )
    return (
        wc.CitationDataOutput(
            document_id=document_id,
            title=title,
            authors=authors,
            publish_date=publish_date,
            journal=journal,
            publisher=publisher,
            doi=doi,
        ),
        any(
            (
                value.document_id != document_id,
                title_truncated,
                authors_truncated,
                publish_date_truncated,
                journal_truncated,
                publisher_truncated,
                doi_truncated,
            )
        ),
    )


def _normalized_scalar(value: object) -> JsonValue | None:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        if value.bit_length() <= 256:
            return value
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (UUID, datetime, date, time, Enum, BaseModel)):
        try:
            return normalize_json_value(value)
        except JsonNormalizationError:
            return None
    return None


def _diagnostic_value(
    value: object,
    *,
    depth: int = 0,
    active_containers: set[int] | None = None,
) -> tuple[JsonValue, bool]:
    """Select a small strict-JSON diagnostic without trusting provider values."""

    if isinstance(value, str):
        return _text(value, max_bytes=CITATION_DIAGNOSTIC_STRING_JSON_BYTES)
    scalar = _normalized_scalar(value)
    if scalar is not None or value is None:
        if isinstance(scalar, (dict, list)):
            return _diagnostic_value(
                scalar,
                depth=depth,
                active_containers=active_containers,
            )
        if isinstance(scalar, str):
            return _text(
                scalar,
                max_bytes=CITATION_DIAGNOSTIC_STRING_JSON_BYTES,
            )
        if (
            isinstance(scalar, int)
            and not isinstance(scalar, bool)
            and scalar.bit_length() > 256
        ):
            return None, True
        return scalar, False

    if depth >= CITATION_DIAGNOSTIC_MAX_DEPTH:
        return None, True
    active = active_containers if active_containers is not None else set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            return None, True
        active.add(identity)
        try:
            projected: dict[str, JsonValue] = {}
            truncated = len(value) > CITATION_DIAGNOSTIC_NESTED_ITEMS
            for key, item in islice(value.items(), CITATION_DIAGNOSTIC_NESTED_ITEMS):
                if not isinstance(key, str):
                    truncated = True
                    continue
                bounded_key, key_truncated = _text(
                    key,
                    max_bytes=CITATION_DIAGNOSTIC_KEY_JSON_BYTES,
                )
                if not bounded_key or bounded_key in projected:
                    truncated = True
                    continue
                bounded_item, item_truncated = _diagnostic_value(
                    item,
                    depth=depth + 1,
                    active_containers=active,
                )
                projected[bounded_key] = bounded_item
                truncated = truncated or key_truncated or item_truncated
            return projected, truncated
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            return None, True
        active.add(identity)
        try:
            projected_items: list[JsonValue] = []
            truncated = len(value) > CITATION_DIAGNOSTIC_NESTED_ITEMS
            for item in value[:CITATION_DIAGNOSTIC_NESTED_ITEMS]:
                bounded_item, item_truncated = _diagnostic_value(
                    item,
                    depth=depth + 1,
                    active_containers=active,
                )
                projected_items.append(bounded_item)
                truncated = truncated or item_truncated
            return projected_items, truncated
        finally:
            active.remove(identity)
    return None, True


def _diagnostic_map(
    value: Mapping[str, object] | None,
    *,
    max_items: int = wc.CITATION_MAX_MAP_ITEMS,
    string_max_bytes: int = CITATION_DIAGNOSTIC_STRING_JSON_BYTES,
) -> tuple[dict[str, JsonValue] | None, bool]:
    if value is None:
        return None, False
    projected: dict[str, JsonValue] = {}
    truncated = len(value) > max_items
    for key, item in islice(value.items(), max_items):
        bounded_key, key_truncated = _text(
            key,
            max_bytes=CITATION_DIAGNOSTIC_KEY_JSON_BYTES,
        )
        if not bounded_key or bounded_key in projected:
            truncated = True
            continue
        bounded_item: JsonValue
        if isinstance(item, str):
            bounded_item, item_truncated = _text(item, max_bytes=string_max_bytes)
        else:
            bounded_item, item_truncated = _diagnostic_value(item)
        projected[bounded_key] = bounded_item
        truncated = truncated or key_truncated or item_truncated
    return projected, truncated


def _steps(
    values: list[CitationStep],
    *,
    prior_data_truncated: Sequence[bool] = (),
) -> tuple[list[wc.CitationStepOutput], bool]:
    projected: list[wc.CitationStepOutput] = []
    truncated = len(values) > wc.CITATION_MAX_STEPS
    for value in values[: wc.CITATION_MAX_STEPS]:
        detail, detail_truncated = _text(
            value.detail,
            max_bytes=CITATION_STEP_DETAIL_JSON_BYTES,
        )
        data, data_truncated = _diagnostic_map(value.data)
        if len(prior_data_truncated) > len(projected):
            data_truncated = data_truncated or prior_data_truncated[len(projected)]
        projected.append(
            wc.CitationStepOutput(
                kind=value.kind,
                detail=detail,
                data=data,
                data_truncated=data_truncated,
            )
        )
        truncated = truncated or detail_truncated or data_truncated
    return projected, truncated


def _bounded_guidance(value: str) -> str:
    return json_bounded_prefix(value, max_bytes=1_000)


def project_paper_citation(outcome: ToolOutcome) -> ToolOutcome:
    envelope = _CitationReadEnvelope.model_validate(outcome.payload)
    document_id = str(envelope.document_id)
    data, data_truncated = _citation_data(
        envelope.data,
        document_id=document_id,
    )
    style, style_truncated = _text(envelope.preferred_style, max_bytes=100)
    missing, missing_truncated = _text_list(
        envelope.missing_fields,
        max_items=wc.CITATION_MAX_MAP_ITEMS,
        item_max_bytes=CITATION_DIAGNOSTIC_KEY_JSON_BYTES,
    )
    content_truncated = any(
        (
            envelope.content_truncated,
            data_truncated,
            style_truncated,
            missing_truncated,
            bool(outcome.artifacts),
            outcome.action is not None,
        )
    )
    source_guidance = (
        CITATION_READ_GUIDANCE
        if content_truncated
        else envelope.guidance or CITATION_READ_GUIDANCE
    )
    guidance, guidance_truncated = _text(source_guidance, max_bytes=1_000)
    if guidance_truncated:
        content_truncated = True
        guidance = CITATION_READ_GUIDANCE
    payload = wc.PaperCitationReadOutput(
        document_id=envelope.document_id,
        preferred_style=style,
        data=data,
        missing_fields=missing,
        complete=envelope.complete,
        content_truncated=content_truncated,
        guidance=_bounded_guidance(guidance),
    )
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        artifacts=[],
        action=None,
    )


def project_resolved_citation(outcome: ToolOutcome) -> ToolOutcome:
    citation = CitationResult.model_validate(outcome.payload)
    payload_mapping = cast(Mapping[str, object], outcome.payload)
    document_id, document_id_truncated = _text(
        citation.document_id,
        max_bytes=64,
    )
    data, data_truncated = _citation_data(
        citation.data,
        document_id=document_id,
    )
    style, style_truncated = _text(citation.preferred_style, max_bytes=100)
    display, display_truncated = _text(citation.style_display, max_bytes=100)
    missing, missing_truncated = _text_list(
        citation.missing_fields,
        max_items=wc.CITATION_MAX_MAP_ITEMS,
        item_max_bytes=CITATION_DIAGNOSTIC_KEY_JSON_BYTES,
    )
    filled, filled_truncated = _diagnostic_map(
        citation.filled_fields,
        string_max_bytes=CITATION_FILLED_FIELD_JSON_BYTES,
    )
    raw_steps = payload_mapping.get("steps")
    prior_step_flags = (
        [
            isinstance(step, Mapping) and step.get("data_truncated") is True
            for step in raw_steps
        ]
        if isinstance(raw_steps, list)
        else []
    )
    steps, steps_truncated = _steps(
        citation.steps,
        prior_data_truncated=prior_step_flags,
    )
    confidence = citation.confidence
    confidence_truncated = confidence is not None and (
        not math.isfinite(confidence) or not 0 <= confidence <= 1
    )
    if confidence_truncated:
        confidence = None
    raw_resource_uri = payload_mapping.get(
        "resource_uri",
        f"scholens://papers/{document_id}",
    )
    if not isinstance(raw_resource_uri, str):
        raw_resource_uri = f"scholens://papers/{document_id}"
        resource_uri_truncated = True
    else:
        raw_resource_uri, resource_uri_truncated = _text(
            raw_resource_uri,
            max_bytes=512,
        )
    prior_truncated = payload_mapping.get("content_truncated") is True
    content_truncated = any(
        (
            prior_truncated,
            document_id_truncated,
            data_truncated,
            style_truncated,
            display_truncated,
            missing_truncated,
            filled_truncated,
            steps_truncated,
            confidence_truncated,
            resource_uri_truncated,
            bool(outcome.artifacts),
            outcome.action is not None,
        )
    )
    payload = wc.ResolvedCitationOutput(
        document_id=document_id,
        preferred_style=style,
        style_display=display,
        data=data,
        method=citation.method,
        missing_fields=missing,
        filled_fields=filled or {},
        confidence=confidence,
        steps=steps,
        resource_uri=raw_resource_uri,
        content_truncated=content_truncated,
        guidance=_bounded_guidance(CITATION_RESOLUTION_GUIDANCE),
    )
    return replace(
        outcome,
        payload=cast(JsonValue, payload.model_dump(mode="json")),
        artifacts=[],
        action=None,
    )


__all__ = [
    "CITATION_READ_GUIDANCE",
    "CITATION_RESOLUTION_GUIDANCE",
    "project_paper_citation",
    "project_resolved_citation",
]
