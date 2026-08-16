"""Compose a TLS database URL from independently injected secret fields."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import quote

from scholens_runtime_contracts import (
    EndpointConfigurationError,
    validate_database_endpoint,
)


def _database_url() -> str:
    required = (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USERNAME",
        "DATABASE_PASSWORD",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing database configuration: {', '.join(missing)}")
    username = quote(os.environ["DATABASE_USERNAME"], safe="")
    password = quote(os.environ["DATABASE_PASSWORD"], safe="")
    try:
        host, port = validate_database_endpoint(
            host=os.environ["DATABASE_HOST"],
            port=os.environ["DATABASE_PORT"],
            environment=os.getenv("ENVIRONMENT", "development"),
        )
    except EndpointConfigurationError as exc:
        raise RuntimeError(str(exc)) from exc
    database = quote(os.environ["DATABASE_NAME"], safe="")
    ca_path = os.getenv("AUTH_PG_SSL_ROOT_CERT", "/etc/ssl/certs/global-bundle.pem")
    return (
        f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
        f"?sslmode=verify-full&sslrootcert={quote(ca_path, safe='/')}"
    )


def _identity_database_url(database_url: str) -> str:
    sqlalchemy_scheme = "postgresql+psycopg2://"
    if not database_url.startswith(sqlalchemy_scheme):
        raise RuntimeError("unsupported application database URL scheme")
    return "postgresql://" + database_url.removeprefix(sqlalchemy_scheme)


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "api"
    database_url = _database_url()
    identity_database_url = _identity_database_url(database_url)
    os.environ["DATABASE_URL"] = database_url
    os.environ["AUTH_DATABASE_URL"] = identity_database_url
    if command == "api":
        executable = ["gunicorn", "-c", "gunicorn.config.py", "app.main:app"]
    elif command == "migrate":
        migration = subprocess.run(
            ["scholens", "db", "upgrade", "--yes", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(migration.stdout)
        if payload.get("up_to_date") is not True:
            raise RuntimeError("Scholens migration did not converge")
        # Identity reads its asyncpg URL from the environment so credentials never
        # enter the process argument list or a CalledProcessError representation.
        subprocess.run(["sanchezcloud-identity", "check-schema"], check=True)
        installed = int(
            subprocess.run(
                ["sanchezcloud-identity", "schema-version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        from sanchezcloud_identity import AUTH_SCHEMA_VERSION

        if installed != AUTH_SCHEMA_VERSION:
            raise RuntimeError(
                "installed auth schema must exactly match the release contract"
            )
        proof = {
            "contract_version": 1,
            "release_sha": os.environ["RELEASE_SHA"],
            "scholens": {
                "current_revisions": payload["current_revisions"],
                "expected_revisions": payload["expected_revisions"],
                "up_to_date": True,
            },
            "identity": {
                "policy": "exact",
                "required_schema_version": AUTH_SCHEMA_VERSION,
                "installed_schema_version": installed,
            },
        }
        sys.stdout.write(
            "SCHOLENS_MIGRATION_PROOF="
            + json.dumps(proof, separators=(",", ":"), sort_keys=True)
            + "\n"
        )
        sys.stdout.flush()
        return 0
    else:
        raise RuntimeError(f"unsupported runtime command: {command}")
    os.execvp(executable[0], executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
