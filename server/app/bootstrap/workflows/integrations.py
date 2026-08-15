"""External validation followed by short integration persistence commands."""

from __future__ import annotations

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.connections.application import (
    IntegrationConnectionResponse,
    IntegrationListResponse,
)
from app.modules.integrations.connections.domain import (
    SEARCH_CONNECTOR_PROVIDERS,
    IntegrationProvider,
)
from app.modules.integrations.connectors.infrastructure.mcp import ConnectorToolResolver
from app.shared.application import Actor, ApplicationExecutor, OperationContext


class IntegrationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        resolver: ConnectorToolResolver,
    ) -> None:
        self._executor = executor
        self._resolver = resolver

    def list(self, *, actor: Actor) -> IntegrationListResponse:
        return self._executor.query(
            lambda capabilities: capabilities.integrations.list(actor=actor)
        )

    async def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
        credential: str,
    ) -> IntegrationConnectionResponse:
        verified = provider in SEARCH_CONNECTOR_PROVIDERS
        if verified:
            await self._resolver.probe(provider=provider, api_key=credential)
        return self._executor.command(
            lambda capabilities: capabilities.integrations.connect(
                actor=actor,
                operation=operation,
                provider=provider,
                credential=credential,
                verified=verified,
            )
        )

    async def set_enabled(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
        enabled: bool,
    ) -> IntegrationConnectionResponse:
        verified = False
        if enabled and provider in SEARCH_CONNECTOR_PROVIDERS:
            credential = self._executor.query(
                lambda capabilities: capabilities.integrations.credential(
                    actor=actor,
                    provider=provider,
                    require_enabled=False,
                )
            )
            await self._resolver.probe(
                provider=provider,
                api_key=credential.secret,
            )
            verified = True
        return self._executor.command(
            lambda capabilities: capabilities.integrations.set_enabled(
                actor=actor,
                operation=operation,
                provider=provider,
                enabled=enabled,
                verified=verified,
            )
        )

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: IntegrationProvider,
    ) -> None:
        self._executor.command(
            lambda capabilities: capabilities.integrations.disconnect(
                actor=actor,
                operation=operation,
                provider=provider,
            )
        )
