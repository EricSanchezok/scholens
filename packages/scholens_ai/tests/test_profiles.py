from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from scholens_ai import (
    AIProfileName,
    AIThinkingEffort,
    AIThinkingMode,
    ProviderConfigurationError,
    build_model,
    profile_model_settings,
    resolve_profile,
)


def test_default_profiles_are_explicit_and_workload_specific() -> None:
    standard = resolve_profile(AIProfileName.STANDARD, environment={})
    deep = resolve_profile(AIProfileName.DEEP, environment={})
    translation = resolve_profile(AIProfileName.TRANSLATION, environment={})
    reflow = resolve_profile(AIProfileName.REFLOW, environment={})

    assert standard.model == "deepseek:deepseek-v4-flash"
    assert standard.thinking is AIThinkingMode.DISABLED
    assert deep.model == "deepseek:deepseek-v4-pro"
    assert deep.thinking is AIThinkingMode.ENABLED
    assert deep.thinking_effort is AIThinkingEffort.MAX
    assert translation.thinking is AIThinkingMode.DISABLED
    assert reflow.thinking is AIThinkingMode.DISABLED


def test_profile_revision_is_stable_and_covers_runtime_policy() -> None:
    baseline = resolve_profile(AIProfileName.STANDARD, environment={})
    repeated = resolve_profile(AIProfileName.STANDARD, environment={})
    changed_model = resolve_profile(
        AIProfileName.STANDARD,
        environment={"SCHOLENS_AI_STANDARD_MODEL": "openai:gpt-5-mini"},
    )
    changed_limit = resolve_profile(
        AIProfileName.STANDARD,
        environment={"SCHOLENS_AI_MAX_INPUT_CHARS": "120000"},
    )

    assert baseline.revision == repeated.revision
    assert baseline.revision != changed_model.revision
    assert baseline.revision != changed_limit.revision


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"SCHOLENS_AI_STANDARD_MODEL": "ambiguous"}, "provider:model"),
        ({"SCHOLENS_AI_STANDARD_MODEL": ":missing-provider"}, "provider:model"),
        ({"SCHOLENS_AI_STANDARD_MODEL": "openai:"}, "provider:model"),
        ({"SCHOLENS_AI_MAX_RETRIES": "not-an-int"}, "must be an integer"),
        ({"SCHOLENS_AI_MAX_RETRIES": "-1"}, "must not be negative"),
        (
            {"SCHOLENS_AI_REQUEST_TIMEOUT_SECONDS": "0"},
            "must be positive",
        ),
        (
            {
                "SCHOLENS_AI_STANDARD_THINKING": "disabled",
                "SCHOLENS_AI_STANDARD_THINKING_EFFORT": "high",
            },
            "must be none",
        ),
        (
            {
                "SCHOLENS_AI_STANDARD_THINKING": "enabled",
                "SCHOLENS_AI_STANDARD_THINKING_EFFORT": "none",
            },
            "is required",
        ),
    ],
)
def test_profile_rejects_invalid_configuration(
    environment: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ProviderConfigurationError, match=message):
        resolve_profile(AIProfileName.STANDARD, environment=environment)


def test_model_settings_preserve_thinking_and_explicit_output_limit() -> None:
    deep = resolve_profile(AIProfileName.DEEP, environment={})
    settings = profile_model_settings(deep, max_output_tokens=4096)

    assert settings["max_tokens"] == 4096
    assert settings["parallel_tool_calls"] is False
    assert settings["thinking"] == "high"
    assert settings["extra_body"] == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_build_model_uses_the_selected_provider_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "test-key")
    profile = resolve_profile(AIProfileName.STANDARD, environment={})

    model = build_model(profile)

    assert isinstance(model, OpenAIChatModel)
    assert model.system == "deepseek"
    assert model.model_name == "deepseek-v4-flash"
    assert str(model.provider.base_url).rstrip("/") == "https://api.deepseek.com"


def test_build_model_requires_an_explicit_provider_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCHOLENS_AI_DEEPSEEK_API_KEY", raising=False)
    profile = resolve_profile(AIProfileName.STANDARD, environment={})

    with pytest.raises(ProviderConfigurationError, match="API_KEY is required"):
        build_model(profile)
