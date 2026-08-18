"""Regression tests for the PR2 server data-quality fixes."""

from __future__ import annotations

from datetime import datetime

import pytest
from app.bootstrap.adapters.citation_provider import _enrichment_title_matches
from app.modules.papers.application.contracts.discovery import EnrichedData
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.domain.citations import CitationFields
from pydantic import ValidationError


def test_document_update_normalizes_date_only_strings() -> None:
    update = DocumentUpdate(publish_date="2017-01-01")
    assert update.publish_date == datetime(2017, 1, 1, 0, 0, 0)


def test_document_update_normalizes_year_month_and_year() -> None:
    assert DocumentUpdate(publish_date="2017-01").publish_date == datetime(2017, 1, 1)
    assert DocumentUpdate(publish_date="2017").publish_date == datetime(2017, 1, 1)


def test_document_update_keeps_datetime_and_none() -> None:
    stamp = datetime(2017, 6, 12, 10, 30)
    assert DocumentUpdate(publish_date=stamp).publish_date == stamp
    assert DocumentUpdate(publish_date=None).publish_date is None


def test_document_update_rejects_invalid_date_strings() -> None:
    with pytest.raises(ValidationError):
        DocumentUpdate(publish_date="not-a-date")
    with pytest.raises(ValidationError):
        DocumentUpdate(publish_date="2017-13-01")


def test_enrichment_title_match_accepts_same_title() -> None:
    fields = CitationFields(title="Attention Is All You Need")
    enriched = EnrichedData(
        publisher="Curran Associates",
        journal="Advances in Neural Information Processing Systems",
        publication_date="2017-06-12",
        title="Attention Is All You Need",
    )
    assert _enrichment_title_matches(fields, enriched) is True


def test_enrichment_title_match_rejects_unrelated_title() -> None:
    fields = CitationFields(title="Attention Is All You Need")
    enriched = EnrichedData(
        publisher="Shenzhen Medical Academy of Research and Translation",
        journal=None,
        publication_date=None,
        title="Diagnostic value of serum markers in colorectal cancer",
    )
    assert _enrichment_title_matches(fields, enriched) is False


def test_enrichment_title_match_tolerates_minor_punctuation_differences() -> None:
    fields = CitationFields(title="Attention Is All You Need")
    enriched = EnrichedData(
        publisher="Curran Associates",
        journal=None,
        publication_date=None,
        title="Attention Is All You Need!",
    )
    assert _enrichment_title_matches(fields, enriched) is True


def test_enrichment_title_match_accepts_missing_enrichment_title() -> None:
    fields = CitationFields(title="Attention Is All You Need")
    enriched = EnrichedData(
        publisher="Curran Associates",
        journal=None,
        publication_date=None,
        title=None,
    )
    assert _enrichment_title_matches(fields, enriched) is True
