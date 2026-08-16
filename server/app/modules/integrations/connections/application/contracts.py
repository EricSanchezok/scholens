"""Transport-neutral contracts for external service connections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.modules.integrations.connections.domain import IntegrationProvider
from pydantic import BaseModel, ConfigDict, Field, SecretStr

IntegrationCategory = Literal["built_in", "parsing", "search", "reference_manager"]
IntegrationConnectionMethod = Literal["built_in", "credential", "oauth"]
IntegrationConnectionState = Literal[
    "disconnected",
    "connected_unverified",
    "connected",
    "disabled",
    "invalid",
]


class IntegrationConnectionResponse(BaseModel):
    provider: IntegrationProvider
    category: IntegrationCategory
    connection_method: IntegrationConnectionMethod
    managed: bool
    state: IntegrationConnectionState
    enabled: bool
    verified_at: datetime | None = None
    last_used_at: datetime | None = None
    last_error_code: str | None = None
    updated_at: datetime | None = None


class IntegrationListResponse(BaseModel):
    items: list[IntegrationConnectionResponse]


class IntegrationConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    credential: SecretStr = Field(min_length=8, max_length=2_048)


class IntegrationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
