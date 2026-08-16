from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.adapters.openalex import UserOpenAlex
from app.bootstrap.workflows.integrations import IntegrationWorkflow
from app.modules.integrations.connections.application.ports import (
    IntegrationCredential,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.papers.application.contracts.discovery import OpenAlexWork
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


class _IntegrationsCapability:
    def __init__(self, executor: _Executor) -> None:
        self._executor = executor
        self.revision = uuid4()
        self.outcomes: list[dict[str, object]] = []
        self.enable_kwargs: dict[str, object] | None = None

    def credential(self, **_kwargs: object) -> IntegrationCredential:
        assert self._executor.active
        return IntegrationCredential(
            provider=IntegrationProvider.OPENALEX,
            secret="private-openalex-key",
            revision=self.revision,
            updated_at=datetime(2026, 8, 16, tzinfo=UTC),
        )

    def connect(self, **kwargs: object) -> object:
        assert self._executor.active
        self._executor.events.append("connect")
        return kwargs

    def set_enabled(self, **kwargs: object) -> object:
        assert self._executor.active
        self._executor.events.append("set_enabled")
        self.enable_kwargs = kwargs
        return kwargs

    def record_outcome(self, **kwargs: object) -> bool:
        assert self._executor.active
        self.outcomes.append(kwargs)
        return True


class _Capabilities:
    def __init__(self, integrations: _IntegrationsCapability) -> None:
        self.integrations = integrations


class _Executor:
    def __init__(self) -> None:
        self.active = False
        self.events: list[str] = []
        self.integrations = _IntegrationsCapability(self)
        self.capabilities = _Capabilities(self.integrations)

    def query(self, callback: Callable[[Any], Any]) -> Any:
        assert not self.active
        self.active = True
        try:
            return callback(self.capabilities)
        finally:
            self.active = False

    def command(self, callback: Callable[[Any], Any]) -> Any:
        assert not self.active
        self.active = True
        try:
            return callback(self.capabilities)
        finally:
            self.active = False


@pytest.mark.asyncio
async def test_openalex_save_probe_runs_before_persistence() -> None:
    executor = _Executor()
    openalex = MagicMock()

    async def probe(*, api_key: str) -> None:
        assert not executor.active
        assert api_key == "private-openalex-key"
        executor.events.append("probe")

    openalex.probe = AsyncMock(side_effect=probe)
    workflow = IntegrationWorkflow(
        executor=executor,  # type: ignore[arg-type]
        resolver=MagicMock(),
        openalex=openalex,
    )

    await workflow.connect(
        actor=_actor(),
        operation=_operation(),
        provider=IntegrationProvider.OPENALEX,
        credential="private-openalex-key",
    )

    assert executor.events == ["probe", "connect"]


@pytest.mark.asyncio
async def test_openalex_reenable_reads_key_then_probes_before_persistence() -> None:
    executor = _Executor()
    openalex = MagicMock()

    async def probe(*, api_key: str) -> None:
        assert not executor.active
        assert api_key == "private-openalex-key"
        executor.events.append("probe")

    openalex.probe = AsyncMock(side_effect=probe)
    workflow = IntegrationWorkflow(
        executor=executor,  # type: ignore[arg-type]
        resolver=MagicMock(),
        openalex=openalex,
    )

    await workflow.set_enabled(
        actor=_actor(),
        operation=_operation(),
        provider=IntegrationProvider.OPENALEX,
        enabled=True,
    )

    assert executor.events == ["probe", "set_enabled"]
    assert executor.integrations.enable_kwargs is not None
    assert (
        executor.integrations.enable_kwargs["expected_credential_revision"]
        == executor.integrations.revision
    )


@pytest.mark.asyncio
async def test_openalex_request_uses_short_credential_and_outcome_transactions() -> (
    None
):
    executor = _Executor()
    client = MagicMock()

    async def find_by_doi(*, api_key: str, doi: str) -> OpenAlexWork:
        assert not executor.active
        assert api_key == "private-openalex-key"
        assert doi == "10.1000/example"
        executor.events.append("provider")
        return OpenAlexWork(id="https://openalex.org/W1", title="A paper")

    client.find_by_doi = AsyncMock(side_effect=find_by_doi)
    openalex = UserOpenAlex(
        executor=executor,  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
        client=client,
    )

    result = await openalex.find_by_doi(
        actor=_actor(),
        operation=_operation(),
        doi="10.1000/example",
    )

    assert result is not None and result.id.endswith("W1")
    assert executor.events == ["provider"]
    assert len(executor.integrations.outcomes) == 1
    outcome = executor.integrations.outcomes[0]
    assert outcome["credential_revision"] == executor.integrations.revision
    assert outcome["outcome"] == "verified"
    assert "private-openalex-key" not in repr(openalex)
