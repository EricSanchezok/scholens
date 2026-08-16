"""Read-only deployment diagnostics."""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import boto3
import click
import httpx
import redis
from botocore.config import Config
from sqlalchemy import text

from app.operator_cli.common import CliState, OutputCommand, emit, safe_error_detail


def _run_check(name: str, check: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return {"name": name, "ok": True, **check()}
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "error": type(exc).__name__,
            "detail": safe_error_detail(exc),
        }


def _configuration() -> dict[str, object]:
    from app.bootstrap.settings import AppSettings

    settings = AppSettings()
    return {"environment": settings.environment, "valid": True}


def _database() -> dict[str, object]:
    from app.database.database import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"reachable": True}


def _migration() -> dict[str, object]:
    from app.operator_cli.database import migration_status

    return migration_status()


def _redis() -> dict[str, object]:
    from app.bootstrap.cache_endpoint import cache_url_from_environment

    url = cache_url_from_environment() or "redis://127.0.0.1:56379/0"
    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    client.ping()
    return {"reachable": True}


def _job_broker() -> dict[str, object]:
    from app.helpers.celery_config import (
        get_celery_broker_url,
        get_celery_transport_options,
    )

    broker_url = get_celery_broker_url()
    if broker_url.startswith("sqs://"):
        options = get_celery_transport_options(broker_url)
        queues = options["predefined_queues"]
        if not isinstance(queues, dict):
            raise RuntimeError("predefined SQS queues are malformed")
        client = boto3.client(
            "sqs",
            region_name=str(options["region"]),
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"max_attempts": 1},
            ),
        )
        for queue in queues.values():
            if not isinstance(queue, dict) or not isinstance(queue.get("url"), str):
                raise RuntimeError("predefined SQS queue URL is malformed")
            client.get_queue_attributes(
                QueueUrl=queue["url"], AttributeNames=["QueueArn"]
            )
        return {
            "reachable": True,
            "transport": "sqs",
            "queues": sorted(queues),
        }

    parsed = urlparse(broker_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5672
    with socket.create_connection((host, port), timeout=1):
        pass
    return {"reachable": True, "transport": "amqp"}


def _jobs() -> dict[str, object]:
    if os.getenv("ENVIRONMENT", "development").casefold() == "production":
        return {"reachable": True, "deployed": False, "mode": "worker-only"}

    response = httpx.get("http://127.0.0.1:7302/health", timeout=2)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "healthy":
        raise RuntimeError("Jobs API did not report healthy")
    return {"reachable": True, "service": body.get("service")}


def _s3() -> dict[str, object]:
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME is required")
    client = boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        endpoint_url=os.getenv("AWS_ENDPOINT_URL_S3"),
        config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1}),
    )
    client.head_bucket(Bucket=bucket)
    return {"reachable": True, "bucket_configured": True}


def _ai_profiles() -> dict[str, object]:
    from scholens_ai import AIProfileName, resolve_profile

    profiles: list[dict[str, Any]] = []
    for name in AIProfileName:
        profile = resolve_profile(name)
        variable = f"SCHOLENS_AI_{profile.provider.upper().replace('-', '_')}_API_KEY"
        profiles.append(
            {
                "profile": name.value,
                "provider": profile.provider,
                "model": profile.model_id,
                "credential_configured": bool(os.getenv(variable)),
            }
        )
    missing = [
        item["profile"] for item in profiles if not item["credential_configured"]
    ]
    if missing:
        raise RuntimeError(
            f"AI credentials are missing for profiles: {', '.join(missing)}"
        )
    return {"profiles": profiles}


@click.command("doctor", cls=OutputCommand)
@click.pass_obj
def doctor_command(state: CliState) -> None:
    """Check dependencies without changing state or calling a model."""
    checks = [
        _run_check("configuration", _configuration),
        _run_check("database", _database),
        _run_check("migration", _migration),
        _run_check("redis", _redis),
        _run_check("job_broker", _job_broker),
        _run_check("jobs_api", _jobs),
        _run_check("s3", _s3),
        _run_check("ai_profiles", _ai_profiles),
    ]
    ok = all(bool(item["ok"]) for item in checks)
    payload = {"ok": ok, "checks": checks}
    human = "\n".join(
        f"{'PASS' if item['ok'] else 'FAIL'}\t{item['name']}" for item in checks
    )
    emit(state, payload, human=human)
    if not ok:
        raise click.exceptions.Exit(1)


__all__ = ["doctor_command"]
