"""External validation followed by short integration persistence commands."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.adapters.openalex import UserOpenAlex
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.connections.application import (
    IntegrationConnectionResponse,
    IntegrationListResponse,
)
from app.modules.integrations.connections.domain import (
    MCP_CONNECTOR_PROVIDERS,
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
        openalex: UserOpenAlex,
    ) -> None:
        self._executor = executor
        self._resolver = resolver
        self._openalex = openalex

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
        verified = provider in MCP_CONNECTOR_PROVIDERS or (
            provider is IntegrationProvider.OPENALEX
        )
        if provider in MCP_CONNECTOR_PROVIDERS:
            await self._resolver.probe(provider=provider, api_key=credential)
        elif provider is IntegrationProvider.OPENALEX:
            await self._openalex.probe(api_key=credential)
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
        credential_revision: UUID | None = None
        if enabled and (
            provider in MCP_CONNECTOR_PROVIDERS
            or provider is IntegrationProvider.OPENALEX
        ):
            credential = self._executor.query(
                lambda capabilities: capabilities.integrations.credential(
                    actor=actor,
                    provider=provider,
                    require_enabled=False,
                )
            )
            credential_revision = credential.revision
            if provider in MCP_CONNECTOR_PROVIDERS:
                await self._resolver.probe(
                    provider=provider,
                    api_key=credential.secret,
                )
            else:
                await self._openalex.probe(api_key=credential.secret)
            verified = True
        return self._executor.command(
            lambda capabilities: capabilities.integrations.set_enabled(
                actor=actor,
                operation=operation,
                provider=provider,
                enabled=enabled,
                verified=verified,
                expected_credential_revision=credential_revision,
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
