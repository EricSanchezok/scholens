from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
from app.modules.papers.application.citations import CitationMetadataPatch
from app.modules.papers.application.contracts.discovery import EnrichedData
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _provider(*, crossref: MagicMock, openalex: MagicMock) -> CitationMetadataProvider:
    return CitationMetadataProvider(
        MagicMock(),
        openalex,
        crossref,
    )


def test_crossref_complete_metadata_does_not_read_openalex_credential() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher="Crossref Publisher",
        publication_date="2025-02-03",
    )
    openalex = MagicMock()

    result = _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.doi == "10.1000/example"
    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher == "Crossref Publisher"
    assert result.patch.publish_date == "2025-02-03T00:00:00"
    openalex.resolve_doi_sync.assert_not_called()
    openalex.enriched_data_sync.assert_not_called()


def test_openalex_fills_only_fields_missing_from_crossref() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher=None,
        publication_date=None,
    )
    openalex = MagicMock()
    openalex.enriched_data_sync.return_value = EnrichedData(
        journal="OpenAlex Journal",
        publisher="OpenAlex Publisher",
        publication_date="2024-11",
    )

    result = _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher == "OpenAlex Publisher"
    assert result.patch.publish_date == "2024-11-01T00:00:00"
    openalex.resolve_doi_sync.assert_not_called()
    openalex.enriched_data_sync.assert_called_once()


def test_missing_openalex_connection_keeps_partial_crossref_result() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher=None,
        publication_date=None,
    )
    openalex = MagicMock()
    openalex.enriched_data_sync.side_effect = AppError(
        code="openalex_credential_required",
        message="OpenAlex connection required",
        kind=FailureKind.CONFLICT,
        retryable=True,
    )

    result = _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.doi == "10.1000/example"
    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher is None


def test_existing_doi_title_mismatch_does_not_mix_another_work_metadata() -> None:
    crossref = MagicMock()
    crossref.enriched_data.return_value = EnrichedData(
        title="An unrelated paper",
        journal="Wrong Journal",
        publisher="Wrong Publisher",
        publication_date="2024-01-01",
    )
    openalex = MagicMock()

    result = _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(
            title="Attention Is All You Need",
            authors=["Ada"],
            doi="10.1000/existing",
        ),
    )

    assert result.patch == CitationMetadataPatch()
    assert result.filled_fields == {}
    assert result.identity_mismatch is True
    openalex.resolve_doi_sync.assert_not_called()
    openalex.enriched_data_sync.assert_not_called()
