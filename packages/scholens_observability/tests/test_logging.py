from __future__ import annotations

import json
import logging

import pytest

from scholens_observability import configure_logging, log_event


def test_structured_logging_redacts_credentials_and_unsafe_objects(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class SecretRepr:
        def __str__(self) -> str:
            return "embedded-password-must-not-appear"

    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging(service="test", environment="production")
        log_event(
            logging.getLogger("tests.observability"),
            logging.ERROR,
            "provider.failed",
            api_key="must-not-appear",
            safe_identifier="visible",
            unsafe_object=SecretRepr(),
            exc_info=RuntimeError("postgres://user:secret@example.invalid/db"),
        )
        output = capsys.readouterr().out.strip()
        payload = json.loads(output)

        assert payload["event"] == "provider.failed"
        assert payload["safe_identifier"] == "visible"
        assert payload["unsafe_object"] == "<SecretRepr>"
        assert payload["exception_type"] == "RuntimeError"
        assert "must-not-appear" not in output
        assert "embedded-password" not in output
        assert "postgres://" not in output
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)


def test_structured_logging_redacts_inline_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging(service="test", environment="production")
        logging.getLogger("tests.observability").error(
            "dependency.failed authorization=Bearer abcdefghijklmnopqrstuvwxyz"
        )
        output = capsys.readouterr().out.strip()

        assert "abcdefghijklmnopqrstuvwxyz" not in output
        assert "[REDACTED]" in output
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)
