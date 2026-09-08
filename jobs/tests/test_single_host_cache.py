"""The worker composition honors the explicit production single-host mode."""

from src.cache_config import cache_url


def test_worker_single_host_cache_requires_production_tls(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RUNTIME_DEPLOYMENT_MODE", "single-host")
    monkeypatch.setenv(
        "CACHE_URL", "rediss://jobs:fixture@cache.personal.svc.sanchezcloud:6380/0"
    )
    assert cache_url() == (
        "rediss://jobs:fixture@cache.personal.svc.sanchezcloud:6380/0"
    )
