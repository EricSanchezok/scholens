"""Frozen v1 integration catalog DTOs; retirement is registered in contracts."""

from datetime import datetime
from typing import Literal

from app.modules.integrations.connections.application import (
    IntegrationConnectionResponse,
)
from app.modules.integrations.connections.application.contracts import (
    IntegrationConnectionMethod,
    IntegrationConnectionState,
)
from pydantic import BaseModel

LegacyIntegrationProvider = Literal[
    "scholight",
    "mineru",
    "anysearch",
    "tavily",
    "exa",
    "firecrawl",
    "openalex",
    "zotero",
]


class LegacyIntegrationConnectionResponse(BaseModel):
    provider: LegacyIntegrationProvider
    category: Literal["built_in", "parsing", "search", "reference_manager"]
    connection_method: IntegrationConnectionMethod
    managed: bool
    state: IntegrationConnectionState
    enabled: bool
    verified_at: datetime | None = None
    last_used_at: datetime | None = None
    last_error_code: str | None = None
    updated_at: datetime | None = None


class LegacyIntegrationListResponse(BaseModel):
    items: list[LegacyIntegrationConnectionResponse]


def legacy_connection(
    value: IntegrationConnectionResponse,
) -> LegacyIntegrationConnectionResponse:
    return LegacyIntegrationConnectionResponse.model_validate(
        value.model_dump(mode="json")
    )
