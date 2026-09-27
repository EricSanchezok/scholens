from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.bootstrap.adapters.openalex import UserOpenAlex
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


@pytest.mark.asyncio
async def test_crossref_complete_metadata_does_not_read_openalex_credential() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher="Crossref Publisher",
        publication_date="2025-02-03",
    )
    openalex = MagicMock(spec=UserOpenAlex)

    result = await _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.doi == "10.1000/example"
    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher == "Crossref Publisher"
    assert result.patch.publish_date == "2025-02-03"
    openalex.resolve_doi.assert_not_called()
    openalex.enriched_data.assert_not_called()


@pytest.mark.asyncio
async def test_openalex_fills_only_fields_missing_from_crossref() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher=None,
        publication_date=None,
    )
    openalex = MagicMock(spec=UserOpenAlex)
    openalex.enriched_data.return_value = EnrichedData(
        journal="OpenAlex Journal",
        publisher="OpenAlex Publisher",
        publication_date="2024-11",
    )

    result = await _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher == "OpenAlex Publisher"
    assert result.patch.publish_date == "2024-11-01"
    openalex.resolve_doi.assert_not_called()
    openalex.enriched_data.assert_called_once()


@pytest.mark.asyncio
async def test_missing_openalex_connection_keeps_partial_crossref_result() -> None:
    crossref = MagicMock()
    crossref.find_doi.return_value = "10.1000/example"
    crossref.enriched_data.return_value = EnrichedData(
        journal="Crossref Journal",
        publisher=None,
        publication_date=None,
    )
    openalex = MagicMock(spec=UserOpenAlex)
    openalex.enriched_data.side_effect = AppError(
        code="openalex_credential_required",
        message="OpenAlex connection required",
        kind=FailureKind.CONFLICT,
        retryable=True,
    )

    result = await _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(),
        operation=_operation(),
        fields=CitationFields(title="A paper", authors=["Ada"]),
    )

    assert result.patch.doi == "10.1000/example"
    assert result.patch.journal == "Crossref Journal"
    assert result.patch.publisher is None


@pytest.mark.asyncio
async def test_existing_doi_title_mismatch_does_not_mix_another_work_metadata() -> None:
    crossref = MagicMock()
    crossref.enriched_data.return_value = EnrichedData(
        title="An unrelated paper",
        journal="Wrong Journal",
        publisher="Wrong Publisher",
        publication_date="2024-01-01",
    )
    openalex = MagicMock(spec=UserOpenAlex)

    result = await _provider(crossref=crossref, openalex=openalex).deterministic(
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
    openalex.resolve_doi.assert_not_called()
    openalex.enriched_data.assert_not_called()


@pytest.mark.asyncio
async def test_deterministic_openalex_reuses_the_callers_event_loop():
    import asyncio

    loop = asyncio.get_running_loop()
    crossref = MagicMock()
    crossref.find_doi.return_value = None
    openalex = MagicMock(spec=UserOpenAlex)

    async def resolve(**_kwargs):
        assert asyncio.get_running_loop() is loop
        return "10.1000/example"

    async def enrich(**_kwargs):
        assert asyncio.get_running_loop() is loop
        return EnrichedData(
            title="A paper",
            journal="Journal",
            publisher="Publisher",
            publication_date="2026",
        )

    openalex.resolve_doi = AsyncMock(side_effect=resolve)
    openalex.enriched_data = AsyncMock(side_effect=enrich)
    result = await _provider(crossref=crossref, openalex=openalex).deterministic(
        actor=_actor(), operation=_operation(), fields=CitationFields(title="A paper")
    )
    assert result.patch.doi == "10.1000/example"
    assert result.patch.publisher == "Publisher"
    openalex.resolve_doi.assert_awaited_once()
    openalex.enriched_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_agentic_resolution_restores_actor_context_and_resets_after_failure():
    from app.llm.token_credits import current_usage_context

    provider = _provider(crossref=MagicMock(), openalex=MagicMock())
    operation = _operation()

    async def recover(**_kwargs):
        context = current_usage_context()
        assert context.user_id == _actor().id
        assert context.operation_id == str(operation.trace.operation_id)
        raise RuntimeError("provider unavailable")

    provider._recovery.find_metadata = AsyncMock(side_effect=recover)
    assert current_usage_context() is None
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await provider.agentic(
            actor=_actor(),
            operation=operation,
            fields=CitationFields(title="Paper"),
            missing_fields=["doi"],
            steps=[],
        )
    assert current_usage_context() is None
