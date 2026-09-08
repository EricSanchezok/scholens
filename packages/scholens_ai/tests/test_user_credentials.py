import pytest
from scholens_ai import (
    AIProfileName,
    ProviderConfigurationError,
    build_model,
    resolve_profile,
)


def test_explicit_deepseek_keys_are_isolated_and_use_official_endpoint(monkeypatch):
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "platform-key")
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_BASE_URL", "https://untrusted.example")
    profile = resolve_profile(AIProfileName.STANDARD, environment={})
    first = build_model(profile, api_key="first-user-key")
    second = build_model(profile, api_key="second-user-key")
    assert first.client.api_key == "first-user-key"
    assert second.client.api_key == "second-user-key"
    assert str(first.client.base_url) == "https://api.deepseek.com"
    with pytest.raises(ProviderConfigurationError):
        build_model(profile, api_key="")
