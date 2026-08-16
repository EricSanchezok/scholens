"""Stable identities and categories for external product integrations."""

from __future__ import annotations

from enum import StrEnum


class IntegrationProvider(StrEnum):
    SCHOLIGHT = "scholight"
    MINERU = "mineru"
    ANYSEARCH = "anysearch"
    TAVILY = "tavily"
    EXA = "exa"
    FIRECRAWL = "firecrawl"
    OPENALEX = "openalex"


BUILT_IN_INTEGRATION = IntegrationProvider.SCHOLIGHT
MCP_CONNECTOR_PROVIDERS = (
    IntegrationProvider.ANYSEARCH,
    IntegrationProvider.TAVILY,
    IntegrationProvider.EXA,
    IntegrationProvider.FIRECRAWL,
)
USER_MANAGED_INTEGRATION_PROVIDERS = (
    IntegrationProvider.MINERU,
    *MCP_CONNECTOR_PROVIDERS,
    IntegrationProvider.OPENALEX,
)
