"""Validated process settings owned by the composition root."""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import Field, IPvAnyNetwork, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.bootstrap.cache_endpoint import cache_url_from_fields

PUBLIC_API_PREFIX = "/api/v1"
WEBHOOK_API_PREFIX = "/webhooks/v1"
INTERNAL_API_PREFIX = "/internal/v1"
_DEVELOPMENT_INTEGRATION_KEY = "ZGV2ZWxvcG1lbnQtaW50ZWdyYXRpb24ta2V5LTMyISE="
_DEVELOPMENT_INVITATION_SECRET = "development-only-invitation-secret"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    release_sha: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    diagnostic_snapshot_bucket: str | None = None
    diagnostic_snapshot_kms_key_id: str | None = None
    diagnostic_success_sample_rate: float = Field(default=0.01, ge=0, le=1)
    trust_cloudflare_client_ip: bool = False
    trusted_proxy_cidr: IPvAnyNetwork | None = None
    client_domain: str = "http://127.0.0.1:7300"
    client_allowed_origins: str | None = None
    paper_search_backend: Literal["postgres_fts"] = "postgres_fts"
    paper_search_cursor_secret: str = Field(
        default="development-only-search-cursor-secret",
        min_length=32,
    )
    project_invitation_token_secret: str = Field(
        default=_DEVELOPMENT_INVITATION_SECRET,
        min_length=32,
    )
    project_invitation_delivery_interval_seconds: float = Field(
        default=1,
        ge=0.1,
        le=60,
    )
    project_invitation_delivery_lease_seconds: float = Field(
        default=45,
        ge=40,
        le=3_600,
    )
    cache_url: str | None = None
    cache_host: str | None = None
    cache_port: int = Field(default=6379, ge=1, le=65535)
    cache_username: str | None = None
    cache_password: str | None = None
    cache_tls: bool = False
    integration_credential_encryption_key: str = _DEVELOPMENT_INTEGRATION_KEY
    scholight_mcp_url: str = "https://scholight.sanchezcloud.net/api/mcp"
    scholight_mcp_delegation_jwt_secret: str | None = None

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Return an explicit browser-origin allowlist with a safe canonical fallback."""
        raw_origins = self.client_allowed_origins or self.client_domain
        origins = (origin.strip() for origin in raw_origins.split(","))
        return list(dict.fromkeys(origin for origin in origins if origin))

    @property
    def resolved_cache_url(self) -> str | None:
        return cache_url_from_fields(
            configured_url=self.cache_url,
            host=self.cache_host,
            port=self.cache_port,
            username=self.cache_username,
            password=self.cache_password,
            tls=self.cache_tls,
            environment=self.environment,
        )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> AppSettings:
        try:
            integration_key = base64.urlsafe_b64decode(
                self.integration_credential_encryption_key.encode()
            )
        except Exception as exc:
            raise ValueError(
                "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(integration_key) != 32:
            raise ValueError(
                "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        if (
            self.environment.casefold() == "production"
            and self.paper_search_cursor_secret
            == "development-only-search-cursor-secret"
        ):
            raise ValueError("PAPER_SEARCH_CURSOR_SECRET is required in production")
        if (
            self.environment.casefold() == "production"
            and self.project_invitation_token_secret == _DEVELOPMENT_INVITATION_SECRET
        ):
            raise ValueError(
                "PROJECT_INVITATION_TOKEN_SECRET is required in production"
            )
        if (
            self.environment.casefold() == "production"
            and self.integration_credential_encryption_key
            == _DEVELOPMENT_INTEGRATION_KEY
        ):
            raise ValueError(
                "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY is required in production"
            )
        if self.environment.casefold() == "production" and (
            self.scholight_mcp_delegation_jwt_secret is None
            or len(self.scholight_mcp_delegation_jwt_secret.encode()) < 32
        ):
            raise ValueError(
                "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET is required in production"
            )
        if (
            self.environment.casefold() == "production"
            and self.trust_cloudflare_client_ip
            and self.trusted_proxy_cidr is None
        ):
            raise ValueError(
                "TRUSTED_PROXY_CIDR is required when Cloudflare client IP is trusted"
            )
        if self.environment.casefold() == "production":
            self.resolved_cache_url
        return self
