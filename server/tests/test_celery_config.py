from __future__ import annotations

import pytest

from app.helpers.celery_config import DEFAULT_WEBHOOK_BASE_URL, get_webhook_base_url


def test_development_webhook_base_uses_documented_loopback_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")

    assert get_webhook_base_url() == DEFAULT_WEBHOOK_BASE_URL


@pytest.mark.parametrize(
    "configured_url",
    [None, "http://127.0.0.1:7301", "http://localhost:7301"],
)
def test_production_webhook_base_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured_url: str | None,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    if configured_url is None:
        monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("WEBHOOK_BASE_URL", configured_url)

    with pytest.raises(RuntimeError):
        get_webhook_base_url()


def test_production_webhook_base_accepts_private_service_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "WEBHOOK_BASE_URL",
        "http://scholens-api.production.svc.sanchezcloud:8000",
    )

    assert get_webhook_base_url() == (
        "http://scholens-api.production.svc.sanchezcloud:8000"
    )
