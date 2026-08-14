"""Scholens-owned AI workload profiles over Pydantic AI providers.

The public model identifier is always ``provider:model``. Pydantic AI owns
provider/model compatibility while Scholens owns deployment configuration,
credentials, thinking policy, and the revision used by caches and audit logs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, cast

import httpx
from openai import AsyncOpenAI
from pydantic_ai import ModelSettings
from pydantic_ai.models import Model, infer_model

PROFILE_SCHEMA_REVISION = "scholens-ai-profile-v1"
DEFAULT_MAX_OUTPUT_TOKENS = 384 * 1024


class AIProfileName(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"
    TRANSLATION = "translation"
    REFLOW = "reflow"


class AIThinkingMode(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"


class AIThinkingEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class ProviderConfigurationError(ValueError):
    """The selected model has no valid Scholens provider configuration."""


_DEFAULTS: dict[AIProfileName, tuple[str, AIThinkingMode, AIThinkingEffort]] = {
    AIProfileName.STANDARD: (
        "deepseek:deepseek-v4-flash",
        AIThinkingMode.DISABLED,
        AIThinkingEffort.NONE,
    ),
    AIProfileName.DEEP: (
        "deepseek:deepseek-v4-pro",
        AIThinkingMode.ENABLED,
        AIThinkingEffort.MAX,
    ),
    AIProfileName.TRANSLATION: (
        "deepseek:deepseek-v4-flash",
        AIThinkingMode.DISABLED,
        AIThinkingEffort.NONE,
    ),
    AIProfileName.REFLOW: (
        "deepseek:deepseek-v4-flash",
        AIThinkingMode.DISABLED,
        AIThinkingEffort.NONE,
    ),
}


@dataclass(frozen=True, slots=True)
class AIProfile:
    name: AIProfileName
    model: str
    provider: str
    model_id: str
    thinking: AIThinkingMode
    thinking_effort: AIThinkingEffort
    request_timeout_seconds: float
    max_output_tokens: int
    max_retries: int
    structured_retries: int
    max_input_chars: int

    @property
    def revision(self) -> str:
        payload = {
            "schema": PROFILE_SCHEMA_REVISION,
            "name": self.name.value,
            "model": self.model,
            "thinking": self.thinking.value,
            "thinking_effort": self.thinking_effort.value,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "max_retries": self.max_retries,
            "structured_retries": self.structured_retries,
            "max_input_chars": self.max_input_chars,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:20]


def _read_int(environment: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(environment.get(name, str(default)))
    except ValueError as exc:
        raise ProviderConfigurationError(f"{name} must be an integer") from exc
    if value < 0:
        raise ProviderConfigurationError(f"{name} must not be negative")
    return value


def _read_positive_float(
    environment: Mapping[str, str], name: str, default: float
) -> float:
    try:
        value = float(environment.get(name, str(default)))
    except ValueError as exc:
        raise ProviderConfigurationError(f"{name} must be a number") from exc
    if value <= 0:
        raise ProviderConfigurationError(f"{name} must be positive")
    return value


def resolve_profile(
    name: AIProfileName,
    *,
    environment: Mapping[str, str] | None = None,
) -> AIProfile:
    values = environment if environment is not None else os.environ
    default_model, default_thinking, default_effort = _DEFAULTS[name]
    prefix = f"SCHOLENS_AI_{name.value.upper()}"
    model = values.get(f"{prefix}_MODEL", default_model).strip()
    provider, separator, model_id = model.partition(":")
    provider = provider.strip().lower()
    model_id = model_id.strip()
    if not separator or not provider or not model_id:
        raise ProviderConfigurationError(
            f"{prefix}_MODEL must use the provider:model format"
        )
    try:
        thinking = AIThinkingMode(
            values.get(f"{prefix}_THINKING", default_thinking.value).strip().lower()
        )
        effort = AIThinkingEffort(
            values.get(f"{prefix}_THINKING_EFFORT", default_effort.value)
            .strip()
            .lower()
        )
    except ValueError as exc:
        raise ProviderConfigurationError(
            f"{prefix} has an invalid thinking configuration"
        ) from exc
    if thinking is AIThinkingMode.DISABLED and effort is not AIThinkingEffort.NONE:
        raise ProviderConfigurationError(
            f"{prefix}_THINKING_EFFORT must be none when thinking is disabled"
        )
    if thinking is AIThinkingMode.ENABLED and effort is AIThinkingEffort.NONE:
        raise ProviderConfigurationError(
            f"{prefix}_THINKING_EFFORT is required when thinking is enabled"
        )
    return AIProfile(
        name=name,
        model=f"{provider}:{model_id}",
        provider=provider,
        model_id=model_id,
        thinking=thinking,
        thinking_effort=effort,
        request_timeout_seconds=_read_positive_float(
            values, "SCHOLENS_AI_REQUEST_TIMEOUT_SECONDS", 120
        ),
        max_output_tokens=_read_int(
            values, "SCHOLENS_AI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS
        ),
        max_retries=_read_int(values, "SCHOLENS_AI_MAX_RETRIES", 2),
        structured_retries=_read_int(values, "SCHOLENS_AI_STRUCTURED_RETRIES", 2),
        max_input_chars=_read_int(values, "SCHOLENS_AI_MAX_INPUT_CHARS", 300_000),
    )


def profile_model_settings(
    profile: AIProfile,
    *,
    max_output_tokens: int | None = None,
) -> ModelSettings:
    settings: ModelSettings = {
        "max_tokens": max_output_tokens or profile.max_output_tokens,
        "timeout": profile.request_timeout_seconds,
        "parallel_tool_calls": False,
    }
    if profile.thinking is AIThinkingMode.ENABLED:
        settings["thinking"] = cast(
            Any,
            "high"
            if profile.thinking_effort is AIThinkingEffort.MAX
            else profile.thinking_effort.value,
        )
    if profile.provider == "deepseek":
        settings["extra_body"] = (
            {
                "thinking": {"type": "enabled"},
                "reasoning_effort": profile.thinking_effort.value,
            }
            if profile.thinking is AIThinkingMode.ENABLED
            else {"thinking": {"type": "disabled"}}
        )
    return settings


def _provider_environment_key(provider: str, suffix: str) -> str:
    normalized = provider.upper().replace("-", "_")
    return f"SCHOLENS_AI_{normalized}_{suffix}"


def _require_api_key(profile: AIProfile) -> str:
    variable = _provider_environment_key(profile.provider, "API_KEY")
    value = os.getenv(variable)
    if not value:
        raise ProviderConfigurationError(f"{variable} is required for {profile.model}")
    return value


def _http_client(profile: AIProfile) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=profile.request_timeout_seconds)


def _provider(profile: AIProfile) -> Any:
    api_key = _require_api_key(profile)
    base_url = os.getenv(_provider_environment_key(profile.provider, "BASE_URL"))
    if profile.provider in {"deepseek", "openai"}:
        from pydantic_ai.providers.deepseek import DeepSeekProvider
        from pydantic_ai.providers.openai import OpenAIProvider

        if profile.provider == "deepseek" and base_url is None:
            base_url = "https://api.deepseek.com"
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=profile.request_timeout_seconds,
            max_retries=profile.max_retries,
        )
        if profile.provider == "deepseek":
            return DeepSeekProvider(openai_client=client)
        return OpenAIProvider(openai_client=client)
    if profile.provider == "moonshotai":
        from pydantic_ai.providers.moonshotai import MoonshotAIProvider

        return MoonshotAIProvider(api_key=api_key, http_client=_http_client(profile))
    if profile.provider == "anthropic":
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=_http_client(profile),
        )
    if profile.provider == "google":
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=_http_client(profile),
        )
    raise ProviderConfigurationError(
        f"Unsupported AI provider {profile.provider!r}; add one provider adapter "
        "instead of guessing an OpenAI-compatible endpoint"
    )


def build_model(
    profile: AIProfile,
    *,
    max_output_tokens: int | None = None,
) -> Model:
    model = infer_model(profile.model, provider_factory=lambda _: _provider(profile))
    Model.__init__(
        model,
        settings=profile_model_settings(
            profile,
            max_output_tokens=max_output_tokens,
        ),
        profile=model.profile,
    )
    return model
