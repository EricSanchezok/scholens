"""Regression tests for the PR2 server data-quality fixes."""

from __future__ import annotations

from datetime import datetime

import pytest
from app.bootstrap.adapters.citation_provider import _enrichment_title_matches
from app.modules.papers.application.contracts.discovery import EnrichedData
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.application.contracts.documents import DocumentResponse
from app.shared.domain.enums import DocumentProcessingStatus
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


def test_document_update_accepts_iso_datetime_strings() -> None:
    # Regression: citation providers produced "2025-02-03T00:00:00" via
    # datetime.isoformat() round-trips, which parse_publication_date rejected,
    # making the PDF postprocess callback 500 and leaking concurrency leases.
    update = DocumentUpdate(publish_date="2025-02-03T00:00:00")
    assert update.publish_date == datetime(2025, 2, 3, 0, 0, 0)


def test_document_update_rejects_invalid_date_strings() -> None:
    with pytest.raises(ValidationError):
        DocumentUpdate(publish_date="not-a-date")
    with pytest.raises(ValidationError):
        DocumentUpdate(publish_date="2017-13-01")


def test_document_update_validate_lenient_drops_only_invalid_fields() -> None:
    update, dropped = DocumentUpdate.validate_lenient(
        {
            "journal": "A Journal",
            "publish_date": "not-a-date",
        }
    )
    assert dropped == ("publish_date",)
    assert update.journal == "A Journal"
    assert update.publish_date is None


def test_document_update_validate_lenient_keeps_valid_updates_untouched() -> None:
    update, dropped = DocumentUpdate.validate_lenient(
        {
            "doi": "10.1000/example",
            "publish_date": "2025-02-03",
        }
    )
    assert dropped == ()
    assert update.doi == "10.1000/example"
    assert update.publish_date == datetime(2025, 2, 3)


def test_document_update_validate_lenient_reports_only_top_level_fields() -> None:
    update, dropped = DocumentUpdate.validate_lenient(
        {
            "journal": "A Journal",
            "field_provenance": {"publish_date": object()},
        }
    )

    assert dropped == ("field_provenance",)
    assert update.journal == "A Journal"
    assert "field_provenance" not in update.model_dump(exclude_unset=True)


def test_document_response_serializes_publish_date_as_rfc3339_utc() -> None:
    response = DocumentResponse(
        document_id="10000000-0000-4000-8000-000000000001",
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        title="Paper",
        authors=None,
        abstract=None,
        institutions=None,
        keywords=None,
        doi=None,
        journal=None,
        publisher=None,
        publish_date=datetime(2017, 1, 1),
        summary=None,
        summary_citations=None,
        starter_questions=None,
        processing_status=DocumentProcessingStatus.COMPLETED,
        parser_quality="full",
        parser_warning_code=None,
        created_at=datetime(2017, 1, 1),
        updated_at=datetime(2017, 1, 1),
    )

    assert response.model_dump(mode="json")["publish_date"] == "2017-01-01T00:00:00Z"
    schema = DocumentResponse.model_json_schema()
    assert schema["properties"]["publish_date"]["anyOf"][0]["format"] == "date-time"


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


def test_enrichment_title_match_rejects_missing_enrichment_title() -> None:
    fields = CitationFields(title="Attention Is All You Need")
    enriched = EnrichedData(
        publisher="Curran Associates",
        journal=None,
        publication_date=None,
        title=None,
    )
    assert _enrichment_title_matches(fields, enriched) is False


def test_enrichment_title_match_normalizes_unicode_and_punctuation() -> None:
    fields = CitationFields(title="Ａttention: Is All You Need?")
    enriched = EnrichedData(
        publisher="Curran Associates",
        journal=None,
        publication_date=None,
        title="Attention — Is All You Need!",
    )
    assert _enrichment_title_matches(fields, enriched) is True
