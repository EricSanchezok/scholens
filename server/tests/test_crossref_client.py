from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
import requests

from app.modules.papers.infrastructure.crossref import CrossrefClient


@pytest.mark.parametrize(
    ("operation", "private_value"),
    [
        ("find_doi", "A private unpublished manuscript title"),
        ("enriched_data", "10.1000/private-doi"),
    ],
)
def test_crossref_failures_do_not_log_research_identifiers(
    operation: str,
    private_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = CrossrefClient()

    with (
        patch(
            "app.modules.papers.infrastructure.crossref.requests.get",
            side_effect=requests.RequestException(private_value),
        ),
        caplog.at_level(logging.WARNING),
    ):
        if operation == "find_doi":
            result = client.find_doi(title=private_value)
        else:
            result = client.enriched_data(doi=private_value)

    assert result is None
    assert private_value not in caplog.text
