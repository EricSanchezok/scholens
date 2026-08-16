from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from scholens_ai import (
    AIProfileName,
    ProviderConfigurationError,
    build_model,
    profile_model_settings,
    resolve_profile,
)


def test_default_profiles_are_explicit_and_translation_never_thinks() -> None:
    standard = resolve_profile(AIProfileName.STANDARD, environment={})
    deep = resolve_profile(AIProfileName.DEEP, environment={})
    translation = resolve_profile(AIProfileName.TRANSLATION, environment={})

    assert standard.model == "deepseek:deepseek-v4-flash"
    assert deep.model == "deepseek:deepseek-v4-pro"
    assert deep.thinking.value == "enabled"
    assert deep.thinking_effort.value == "max"
    assert translation.thinking.value == "disabled"
    assert profile_model_settings(translation)["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_profile_revision_changes_with_model_and_thinking_policy() -> None:
    baseline = resolve_profile(AIProfileName.STANDARD, environment={})
    changed_model = resolve_profile(
        AIProfileName.STANDARD,
        environment={"SCHOLENS_AI_STANDARD_MODEL": "google:gemini-2.5-pro"},
    )
    changed_thinking = resolve_profile(
        AIProfileName.STANDARD,
        environment={
            "SCHOLENS_AI_STANDARD_THINKING": "enabled",
            "SCHOLENS_AI_STANDARD_THINKING_EFFORT": "medium",
        },
    )

    assert baseline.revision != changed_model.revision
    assert baseline.revision != changed_thinking.revision


def test_profile_rejects_ambiguous_model_and_invalid_thinking_pair() -> None:
    with pytest.raises(ProviderConfigurationError, match="provider:model"):
        resolve_profile(
            AIProfileName.STANDARD,
            environment={"SCHOLENS_AI_STANDARD_MODEL": "ambiguous-model"},
        )
    with pytest.raises(ProviderConfigurationError, match="must be none"):
        resolve_profile(
            AIProfileName.TRANSLATION,
            environment={
                "SCHOLENS_AI_TRANSLATION_THINKING": "disabled",
                "SCHOLENS_AI_TRANSLATION_THINKING_EFFORT": "high",
            },
        )
    with pytest.raises(ProviderConfigurationError, match="Unsupported AI provider"):
        resolve_profile(
            AIProfileName.STANDARD,
            environment={"SCHOLENS_AI_STANDARD_MODEL": "openai:gpt-5-mini"},
        )


def test_model_prefix_selects_provider_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "test-key")
    profile = resolve_profile(AIProfileName.STANDARD, environment={})

    model = build_model(profile)

    assert isinstance(model, OpenAIChatModel)
    assert model.system == "deepseek"
    assert model.model_name == "deepseek-v4-flash"
    assert str(model.provider.base_url).rstrip("/") == "https://api.deepseek.com"
