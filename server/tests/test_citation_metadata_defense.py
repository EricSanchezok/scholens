"""Field-level defense of the citation metadata write-back path.

``SqlAlchemyCitationMetadataStore.apply_missing`` converges on the strict
``DocumentUpdate`` write contract. A malformed field from an external
citation provider (for example an unparseable ``publish_date``) must be
dropped instead of failing the whole write: the remaining valid fields
still apply, the dropped field is logged, and a patch whose only change
was invalid still completes safely.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.adapters.citation_metadata import SqlAlchemyCitationMetadataStore
from app.bootstrap.adapters.project_documents import ProjectDocumentRepository
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    normalize_citation_metadata_patch,
)
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_CAPACITY_COLUMNS,
    DOCUMENT_CITATION_COLUMNS,
    DOCUMENT_STORAGE_REFERENCE_COLUMNS,
    DocumentColumns,
)
from app.shared.application import Actor
from sqlalchemy.dialects import postgresql


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _paper(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "doi": None,
        "journal": None,
        "publisher": None,
        "publish_date": None,
        "field_provenance": None,
        "title": "Paper",
        "authors": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _store(
    monkeypatch: pytest.MonkeyPatch, paper: SimpleNamespace
) -> tuple[SqlAlchemyCitationMetadataStore, MagicMock]:
    repository = MagicMock()
    repository.find_accessible.return_value = paper
    repository.update_canonical.return_value = paper
    monkeypatch.setattr(
        "app.bootstrap.adapters.citation_metadata.document_repository", repository
    )
    return SqlAlchemyCitationMetadataStore(MagicMock()), repository


def test_apply_missing_drops_invalid_publish_date_and_keeps_valid_fields(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, repository = _store(monkeypatch, _paper())

    with caplog.at_level(logging.WARNING):
        result = store.apply_missing(
            actor=_actor(),
            document_id=uuid4(),
            project_id=None,
            patch=CitationMetadataPatch(
                publish_date="not-a-date",
                journal="Nature",
            ),
        )

    assert result.changed is True
    update = repository.update_canonical.call_args.kwargs["update"]
    assert update.journal == "Nature"
    assert "publish_date" not in update.model_dump(exclude_unset=True)
    assert repository.update_canonical.call_args.kwargs["refresh_result"] is False
    assert any(
        record.message == "citation.metadata.dropped_invalid_fields"
        for record in caplog.records
    )


def test_apply_missing_is_safe_when_only_publish_date_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, repository = _store(monkeypatch, _paper())

    result = store.apply_missing(
        actor=_actor(),
        document_id=uuid4(),
        project_id=None,
        patch=CitationMetadataPatch(publish_date="not-a-date"),
    )

    assert result.changed is False
    repository.update_canonical.assert_not_called()


def test_new_provider_fields_are_normalized_without_rewriting_historical_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical_journal = "historical" * 10_000
    store, _repository = _store(
        monkeypatch,
        _paper(
            doi="legacy non-standard identifier",
            journal=historical_journal,
            publish_date="legacy-date",
        ),
    )

    historical = store.read(
        actor=_actor(),
        document_id=uuid4(),
        project_id=None,
    )
    normalized, dropped = normalize_citation_metadata_patch(
        CitationMetadataPatch(
            doi="not-a-doi",
            journal="x" * 1_001,
            publisher="  Scholens Press  ",
            publish_date="x" * 1_000,
            field_provenance={
                "publisher": {
                    "source_url": "https://example.test/" + "x" * 3_000,
                    "filled_by": "resolver",
                    "confidence": 2.0,
                    "filled_at": "2026-08-24T00:00:00+00:00",
                    "unknown": "not persisted",
                },
                "unknown_field": {"filled_by": "resolver"},
            },
        )
    )

    assert historical is not None
    assert historical.doi == "legacy non-standard identifier"
    assert historical.journal == historical_journal
    assert historical.publish_date == "legacy-date"
    assert normalized.doi is None
    assert normalized.journal is None
    assert normalized.publisher == "Scholens Press"
    assert normalized.publish_date is None
    assert normalized.field_provenance == {
        "publisher": {
            "filled_by": "resolver",
            "filled_at": "2026-08-24T00:00:00+00:00",
        }
    }
    assert set(dropped) == {
        "doi",
        "field_provenance",
        "journal",
        "publish_date",
    }


def test_optional_null_provenance_is_canonicalized_without_false_warning() -> None:
    normalized, dropped = normalize_citation_metadata_patch(
        CitationMetadataPatch(
            journal="Journal",
            field_provenance={
                "journal": {
                    "source_url": None,
                    "filled_by": "resolver",
                    "confidence": 0.9,
                    "filled_at": "2026-08-24T00:00:00+00:00",
                }
            },
        )
    )

    assert dropped == ()
    assert normalized.field_provenance == {
        "journal": {
            "filled_by": "resolver",
            "confidence": 0.9,
            "filled_at": "2026-08-24T00:00:00+00:00",
        }
    }


def test_project_citation_uses_the_explicit_citation_column_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = _paper()
    project_documents = MagicMock()
    project_documents.get_paper_by_project.return_value = paper
    monkeypatch.setattr(
        "app.bootstrap.adapters.citation_metadata.project_document_repository",
        project_documents,
    )

    result = SqlAlchemyCitationMetadataStore(MagicMock()).read(
        actor=_actor(),
        document_id=uuid4(),
        project_id=uuid4(),
    )

    assert result is not None
    assert (
        project_documents.get_paper_by_project.call_args.kwargs["document_columns"]
        == DOCUMENT_CITATION_COLUMNS
    )


@pytest.mark.parametrize(
    "columns",
    [
        DOCUMENT_CITATION_COLUMNS,
        DOCUMENT_CAPACITY_COLUMNS,
        DOCUMENT_STORAGE_REFERENCE_COLUMNS,
    ],
)
def test_project_document_lookup_never_selects_unrequested_large_columns(
    monkeypatch: pytest.MonkeyPatch,
    columns: DocumentColumns,
) -> None:
    db = MagicMock()
    expected = SimpleNamespace(id=uuid4())
    db.scalar.return_value = expected
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_documents.require_project_access",
        MagicMock(),
    )

    loaded = ProjectDocumentRepository().get_paper_by_project(
        db,
        document_id=expected.id,
        project_id=uuid4(),
        user=_actor(),
        document_columns=columns,
    )

    assert loaded is expected
    statement = db.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "documents.raw_content" not in sql
    assert "documents.page_offset_map" not in sql
    assert "documents.summary_citations" not in sql
    assert "documents.parser_archive_s3_key" not in sql
    for column in columns:
        assert f"documents.{column.key}" in sql
