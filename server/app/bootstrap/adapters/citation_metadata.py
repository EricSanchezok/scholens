"""SQLAlchemy persistence adapter for citation metadata."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.bootstrap.adapters.project_documents import project_document_repository
from app.database.models import Document
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    CitationMetadataWrite,
    normalize_citation_metadata_patch,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.domain.citations import CitationFields, fields_from_paper
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_CITATION_COLUMNS,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor

logger = logging.getLogger(__name__)


class SqlAlchemyCitationMetadataStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _paper(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> Document | None:
        if project_id is not None:
            return project_document_repository.get_paper_by_project(
                self._db,
                document_id=document_id,
                project_id=project_id,
                user=actor,
                document_columns=DOCUMENT_CITATION_COLUMNS,
            )
        return document_repository.find_accessible(
            self._db,
            document_id=str(document_id),
            user=actor,
            document_columns=DOCUMENT_CITATION_COLUMNS,
        )

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        return fields_from_paper(paper) if paper is not None else None

    def apply_missing(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        patch: CitationMetadataPatch,
    ) -> CitationMetadataWrite:
        paper = self._paper(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if paper is None:
            return CitationMetadataWrite(CitationFields(), changed=False)

        patch, provider_dropped_fields = normalize_citation_metadata_patch(patch)

        candidates = {
            "doi": patch.doi,
            "journal": patch.journal,
            "publisher": patch.publisher,
            "publish_date": patch.publish_date,
        }
        changes: dict[str, object] = {
            field_name: value
            for field_name, value in candidates.items()
            if value is not None and getattr(paper, field_name) is None
        }
        if patch.field_provenance is not None and changes:
            provenance = dict(paper.field_provenance or {})
            provenance.update(
                {
                    field_name: patch.field_provenance[field_name]
                    for field_name in changes
                    if field_name in patch.field_provenance
                }
            )
            changes["field_provenance"] = provenance
        if not changes:
            if provider_dropped_fields:
                logger.warning(
                    "citation.metadata.dropped_invalid_fields",
                    extra={
                        "document_id": str(document_id),
                        "dropped_fields": provider_dropped_fields,
                    },
                )
            return CitationMetadataWrite(fields_from_paper(paper), changed=False)

        update, dropped_fields = DocumentUpdate.validate_lenient(changes)
        dropped_fields = tuple(sorted(set((*provider_dropped_fields, *dropped_fields))))
        if dropped_fields:
            logger.warning(
                "citation.metadata.dropped_invalid_fields",
                extra={
                    "document_id": str(document_id),
                    "dropped_fields": dropped_fields,
                },
            )
        if not update.model_dump(exclude_unset=True):
            return CitationMetadataWrite(fields_from_paper(paper), changed=False)
        updated = document_repository.update_canonical(
            self._db,
            document=paper,
            update=update,
            user=actor,
            # The assigned citation columns already contain the authoritative
            # values. A full refresh would reload raw_content and every other
            # deferred Document payload solely to return these same fields.
            refresh_result=False,
        )
        return CitationMetadataWrite(
            fields=fields_from_paper(updated or paper),
            changed=updated is not None,
        )


__all__ = ["SqlAlchemyCitationMetadataStore"]
