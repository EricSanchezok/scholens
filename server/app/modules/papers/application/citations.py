"""Citation metadata persistence and transport-neutral result construction."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol
from uuid import UUID

from app.helpers.parser import parse_publication_date
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationMethod,
    CitationResult,
    CitationStep,
)
from app.modules.papers.domain import normalize_doi
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue

PAPER_CITATION_METADATA_UPDATED = OperationAction("paper.citation_metadata_updated")

CITATION_DOI_MAX_CHARACTERS = 500
CITATION_VENUE_MAX_CHARACTERS = 1_000
CITATION_PROVENANCE_SOURCE_URL_MAX_CHARACTERS = 2_048
CITATION_PROVENANCE_WRITER_MAX_CHARACTERS = 100
CITATION_PROVENANCE_TIMESTAMP_MAX_CHARACTERS = 64


@dataclass(frozen=True, slots=True)
class CitationMetadataPatch:
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    publish_date: str | None = None
    field_provenance: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class CitationMetadataWrite:
    fields: CitationFields
    changed: bool


def _normalized_text(value: str | None, *, max_characters: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_characters:
        return None
    return normalized


def _normalized_provenance(
    value: dict[str, JsonValue] | None,
    *,
    field_names: set[str],
) -> tuple[dict[str, JsonValue] | None, bool]:
    if value is None:
        return None, False
    normalized: dict[str, JsonValue] = {}
    invalid = any(field_name not in field_names for field_name in value)
    allowed_keys = {"source_url", "filled_by", "confidence", "filled_at"}
    for field_name in sorted(field_names):
        entry = value.get(field_name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            invalid = True
            continue
        invalid = invalid or any(key not in allowed_keys for key in entry)
        projected: dict[str, JsonValue] = {}
        source_url = entry.get("source_url")
        if source_url is not None:
            if isinstance(source_url, str) and 0 < len(source_url) <= (
                CITATION_PROVENANCE_SOURCE_URL_MAX_CHARACTERS
            ):
                projected["source_url"] = source_url
            else:
                invalid = True
        filled_by = entry.get("filled_by")
        if filled_by is not None:
            if isinstance(filled_by, str) and 0 < len(filled_by) <= (
                CITATION_PROVENANCE_WRITER_MAX_CHARACTERS
            ):
                projected["filled_by"] = filled_by
            else:
                invalid = True
        confidence = entry.get("confidence")
        if confidence is not None:
            if (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and math.isfinite(float(confidence))
                and 0 <= float(confidence) <= 1
            ):
                projected["confidence"] = float(confidence)
            else:
                invalid = True
        filled_at = entry.get("filled_at")
        if filled_at is not None:
            if isinstance(filled_at, str) and 0 < len(filled_at) <= (
                CITATION_PROVENANCE_TIMESTAMP_MAX_CHARACTERS
            ):
                projected["filled_at"] = filled_at
            else:
                invalid = True
        if projected:
            normalized[field_name] = projected
    return normalized or None, invalid


def normalize_citation_metadata_patch(
    patch: CitationMetadataPatch,
) -> tuple[CitationMetadataPatch, tuple[str, ...]]:
    """Validate new provider fields without rewriting historical citation data."""

    dropped: list[str] = []
    raw_doi = patch.doi.strip() if patch.doi is not None else None
    doi = (
        normalize_doi(raw_doi)
        if raw_doi is not None and len(raw_doi) <= CITATION_DOI_MAX_CHARACTERS
        else None
    )
    if patch.doi is not None and (
        doi is None or len(doi) > CITATION_DOI_MAX_CHARACTERS
    ):
        doi = None
        dropped.append("doi")
    journal = _normalized_text(
        patch.journal,
        max_characters=CITATION_VENUE_MAX_CHARACTERS,
    )
    if patch.journal is not None and journal is None:
        dropped.append("journal")
    publisher = _normalized_text(
        patch.publisher,
        max_characters=CITATION_VENUE_MAX_CHARACTERS,
    )
    if patch.publisher is not None and publisher is None:
        dropped.append("publisher")
    raw_publish_date = (
        patch.publish_date.strip() if patch.publish_date is not None else None
    )
    parsed_date = (
        parse_publication_date(raw_publish_date)
        if raw_publish_date is not None
        and len(raw_publish_date) <= CITATION_PROVENANCE_TIMESTAMP_MAX_CHARACTERS
        else None
    )
    publish_date = parsed_date.date().isoformat() if parsed_date is not None else None
    if patch.publish_date is not None and publish_date is None:
        dropped.append("publish_date")
    field_names = {
        field_name
        for field_name, value in {
            "doi": doi,
            "journal": journal,
            "publisher": publisher,
            "publish_date": publish_date,
        }.items()
        if value is not None
    }
    provenance, provenance_invalid = _normalized_provenance(
        patch.field_provenance,
        field_names=field_names,
    )
    if provenance_invalid:
        dropped.append("field_provenance")
    return (
        CitationMetadataPatch(
            doi=doi,
            journal=journal,
            publisher=publisher,
            publish_date=publish_date,
            field_provenance=provenance,
        ),
        tuple(sorted(set(dropped))),
    )


class CitationMetadataStore(Protocol):
    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None: ...

    def apply_missing(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationMetadataWrite: ...


class CitationMetadata:
    """Read citation facts and atomically apply provider findings."""

    def __init__(
        self,
        store: CitationMetadataStore,
        *,
        journal: OperationJournal,
    ) -> None:
        self._store = store
        self._journal = journal

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        return self._store.read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )

    def apply_missing(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationFields:
        result = self._store.apply_missing(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
            patch=patch,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PAPER_CITATION_METADATA_UPDATED,
                resources=(ResourceRef("document", str(document_id)),),
            )
        return result.fields


def build_citation_result(
    *,
    document_id: UUID,
    canonical_style: str,
    style_display: str,
    fields: CitationFields,
    method: CitationMethod,
    missing_fields: list[str],
    filled_fields: dict[str, object],
    confidence: float | None,
    steps: list[CitationStep],
) -> CitationResult:
    steps.append(
        CitationStep(
            kind="resolve",
            detail=f"Resolved citation metadata; preferred style {style_display}.",
            data={"missing": missing_fields},
        )
    )
    return CitationResult(
        document_id=str(document_id),
        preferred_style=canonical_style,
        style_display=style_display,
        data=CitationData(
            document_id=str(document_id),
            title=fields.title,
            authors=fields.authors,
            publish_date=fields.publish_date,
            journal=fields.journal,
            publisher=fields.publisher,
            doi=fields.doi,
        ),
        method=method,
        missing_fields=missing_fields,
        filled_fields=filled_fields,
        confidence=confidence,
        steps=steps,
    )


__all__ = [
    "CitationMetadata",
    "CitationMetadataPatch",
    "CitationMetadataStore",
    "CitationMetadataWrite",
    "build_citation_result",
    "normalize_citation_metadata_patch",
]
