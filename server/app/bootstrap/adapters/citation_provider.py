"""External citation metadata providers with no persistence responsibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import unicodedata
from typing import TYPE_CHECKING

from app.helpers.parser import parse_publication_date
from app.llm.citation_recovery import MetadataRecoveryAgent
from app.modules.integrations.connectors.infrastructure.mcp import ConnectorToolResolver
from app.modules.papers.application.citations import CitationMetadataPatch
from app.modules.papers.application.contracts.citation import CitationStep
from app.modules.papers.application.contracts.discovery import EnrichedData
from app.modules.papers.domain import normalize_doi
from app.modules.papers.domain.citations import CitationFields
from app.modules.papers.infrastructure.crossref import CrossrefClient
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, JsonValue

if TYPE_CHECKING:
    from app.bootstrap.adapters.openalex import UserOpenAlex


@dataclass(frozen=True, slots=True)
class CitationProviderResult:
    patch: CitationMetadataPatch
    filled_fields: dict[str, object]
    confidence: float | None = None
    identity_mismatch: bool = False


class CitationMetadataProvider:
    def __init__(
        self,
        connector_tools: ConnectorToolResolver,
        openalex: UserOpenAlex,
        crossref: CrossrefClient | None = None,
    ) -> None:
        self._recovery = MetadataRecoveryAgent(connector_tools)
        self._openalex = openalex
        self._crossref = crossref or CrossrefClient()

    def deterministic(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        fields: CitationFields,
    ) -> CitationProviderResult:
        doi = fields.doi
        doi_title_verified = False
        if not doi and fields.title:
            doi = self._crossref.find_doi(
                title=fields.title,
                authors=fields.authors or None,
            )
            # Crossref's lookup accepts a DOI only when the returned title is
            # an exact case-insensitive match for the requested title.
            doi_title_verified = doi is not None

        journal = fields.journal
        publisher = fields.publisher
        publish_date = fields.publish_date
        if doi and (not journal or not publisher or not publish_date):
            enriched = self._crossref.enriched_data(doi=doi)
            if _enrichment_title_matches(
                fields,
                enriched,
                allow_missing_title=doi_title_verified,
            ):
                journal, publisher, publish_date = _merge_enriched(
                    enriched=enriched,
                    journal=journal,
                    publisher=publisher,
                    publish_date=publish_date,
                )
            else:
                # Never combine metadata from a newly discovered work with an
                # existing DOI. A mismatch on caller-owned DOI metadata is not
                # enough evidence to overwrite or reinterpret that record.
                if fields.doi:
                    return CitationProviderResult(
                        patch=CitationMetadataPatch(),
                        filled_fields={},
                        identity_mismatch=True,
                    )
                doi = None
                doi_title_verified = False

        if not doi and fields.title:
            try:
                doi = self._openalex.resolve_doi_sync(
                    actor=actor,
                    operation=operation,
                    title=fields.title,
                    authors=fields.authors or None,
                )
                doi_title_verified = False
            except AppError as exc:
                if not _is_skippable_openalex_error(exc):
                    raise

        if doi and (not journal or not publisher or not publish_date):
            try:
                enriched = self._openalex.enriched_data_sync(
                    actor=actor,
                    operation=operation,
                    doi=doi,
                )
            except AppError as exc:
                if not _is_skippable_openalex_error(exc):
                    raise
            else:
                if _enrichment_title_matches(
                    fields,
                    enriched,
                    allow_missing_title=doi_title_verified,
                ):
                    journal, publisher, publish_date = _merge_enriched(
                        enriched=enriched,
                        journal=journal,
                        publisher=publisher,
                        publish_date=publish_date,
                    )
                else:
                    if fields.doi:
                        return CitationProviderResult(
                            patch=CitationMetadataPatch(),
                            filled_fields={},
                            identity_mismatch=True,
                        )
                    doi = None

        filled: dict[str, object] = {
            field_name: value
            for field_name, value in {
                "doi": doi if not fields.doi else None,
                "journal": journal if not fields.journal else None,
                "publisher": publisher if not fields.publisher else None,
                "publish_date": publish_date if not fields.publish_date else None,
            }.items()
            if value is not None
        }
        return CitationProviderResult(
            patch=CitationMetadataPatch(
                doi=str(filled["doi"]) if "doi" in filled else None,
                journal=(str(filled["journal"]) if "journal" in filled else None),
                publisher=(str(filled["publisher"]) if "publisher" in filled else None),
                publish_date=(
                    str(filled["publish_date"]) if "publish_date" in filled else None
                ),
            ),
            filled_fields=filled,
        )

    def agentic(
        self,
        *,
        actor: Actor,
        fields: CitationFields,
        missing_fields: list[str],
        steps: list[CitationStep],
        filled_by: str = "get_paper_citation",
    ) -> CitationProviderResult:
        findings, confidence = self._recovery.find_metadata(
            actor=actor,
            fields=fields,
            missing_fields=missing_fields,
            steps=steps,
        )
        if not findings:
            return CitationProviderResult(
                patch=CitationMetadataPatch(),
                filled_fields={},
                confidence=confidence,
            )

        doi_value = findings.get("doi")
        doi = normalize_doi(str(doi_value)) if doi_value else None
        publish_date_value = findings.get("publish_date")
        parsed_date = (
            parse_publication_date(str(publish_date_value))
            if publish_date_value
            else None
        )
        values = {
            "journal": _optional_string(findings.get("journal")),
            "publisher": _optional_string(findings.get("publisher")),
            "doi": doi,
            # date-only ISO: parse_publication_date and DocumentUpdate.publish_date
            # reject ISO datetime strings such as "2025-02-03T00:00:00".
            "publish_date": parsed_date.date().isoformat() if parsed_date else None,
        }
        filled: dict[str, object] = {
            field_name: value
            for field_name, value in values.items()
            if value is not None and getattr(fields, field_name) is None
        }
        now = datetime.now(timezone.utc).isoformat()
        source_url = _optional_string(findings.get("source_url"))
        provenance: dict[str, JsonValue] = {
            field_name: {
                "source_url": source_url,
                "filled_by": filled_by,
                "confidence": confidence,
                "filled_at": now,
            }
            for field_name in filled
        }
        return CitationProviderResult(
            patch=CitationMetadataPatch(
                doi=str(filled["doi"]) if "doi" in filled else None,
                journal=(str(filled["journal"]) if "journal" in filled else None),
                publisher=(str(filled["publisher"]) if "publisher" in filled else None),
                publish_date=(
                    str(filled["publish_date"]) if "publish_date" in filled else None
                ),
                field_provenance=provenance,
            ),
            filled_fields=filled,
            confidence=confidence,
        )


def _optional_string(value: object) -> str | None:
    return str(value) if value else None


def _enrichment_title_matches(
    fields: CitationFields,
    enriched: EnrichedData | None,
    *,
    allow_missing_title: bool = False,
) -> bool:
    """Whether an enrichment result plausibly describes the requested paper.

    Crossref/OpenAlex title search can return a top hit whose bibliographic
    fields belong to a different work (observed in production: a paper was
    enriched with an unrelated publisher and DOI). When the requested title
    is known, a similarity score below 0.8 means the enrichment is not for
    this paper; the caller then discards the DOI and leaves the fields
    missing so a later recovery pass can retry.
    """
    requested = fields.title
    if not requested:
        return True
    if enriched is None or not enriched.title:
        return allow_missing_title
    requested_title = _normalize_title(requested)
    enriched_title = _normalize_title(enriched.title)
    if not requested_title or not enriched_title:
        return False
    return (
        difflib.SequenceMatcher(
            None,
            requested_title,
            enriched_title,
        ).ratio()
        >= 0.8
    )


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(
        "".join(
            character if character.isalnum() else " " for character in normalized
        ).split()
    )


def _merge_enriched(
    *,
    enriched: EnrichedData | None,
    journal: str | None,
    publisher: str | None,
    publish_date: str | None,
) -> tuple[str | None, str | None, str | None]:
    if enriched is None:
        return journal, publisher, publish_date
    enriched_journal = enriched.journal
    enriched_publisher = enriched.publisher
    publication_date = enriched.publication_date
    if not publish_date and publication_date:
        parsed = parse_publication_date(str(publication_date))
        publish_date = parsed.date().isoformat() if parsed is not None else None
    return journal or enriched_journal, publisher or enriched_publisher, publish_date


def _is_skippable_openalex_error(exc: AppError) -> bool:
    return exc.code in {
        "openalex_credential_required",
        "openalex_credential_invalid",
        "openalex_rate_limited",
        "openalex_unavailable",
    }


__all__ = ["CitationMetadataProvider", "CitationProviderResult"]
