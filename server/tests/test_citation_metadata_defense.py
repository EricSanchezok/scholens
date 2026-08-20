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
from app.modules.papers.application.citations import CitationMetadataPatch
from app.shared.application import Actor


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
