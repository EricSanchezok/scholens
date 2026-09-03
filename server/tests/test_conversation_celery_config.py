from __future__ import annotations

from app.modules.conversations.infrastructure.celery_app import (
    _conversation_worker_pool,
)


def test_conversation_worker_uses_solo_pool_outside_production(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert _conversation_worker_pool() == "solo"

    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert _conversation_worker_pool() == "solo"


def test_conversation_worker_uses_prefork_pool_in_production(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert _conversation_worker_pool() == "prefork"
