"""Compose a TLS database URL from independently injected secret fields."""

from __future__ import annotations

import os
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


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "api"
    database_url = _database_url()
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("AUTH_DATABASE_URL", database_url)
    if command == "api":
        executable = ["gunicorn", "-c", "gunicorn.config.py", "app.main:app"]
    elif command == "migrate":
        executable = ["scholens", "db", "upgrade", "--yes", "--json"]
    else:
        raise RuntimeError(f"unsupported runtime command: {command}")
    os.execvp(executable[0], executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
