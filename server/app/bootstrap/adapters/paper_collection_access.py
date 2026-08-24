"""SQL adapter for document membership in a model-tool paper collection."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.collection_access import PaperCollectionAccessPort
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    PersonalLibraryPaperCollection,
    SelectedPaperCollection,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document, LibraryPaper
from app.modules.projects.infrastructure.access import get_project_access
from app.modules.projects.infrastructure.models import ProjectPaper
from app.shared.application import Actor
from sqlalchemy import select
from sqlalchemy.orm import Session


class SqlPaperCollectionAccess(PaperCollectionAccessPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def contains(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
        document_id: UUID,
    ) -> bool:
        if isinstance(collection, LibraryPaperCollection):
            return self._document_is_accessible(
                actor=actor,
                document_id=document_id,
            )
        if isinstance(collection, PersonalLibraryPaperCollection):
            return (
                self._session.scalar(
                    select(LibraryPaper.document_id).where(
                        LibraryPaper.document_id == document_id,
                        LibraryPaper.user_id == actor.id,
                    )
                )
                is not None
            )
        assert isinstance(collection, SelectedPaperCollection)
        if document_id in collection.document_ids:
            return self._document_is_accessible(
                actor=actor,
                document_id=document_id,
            )
        for project_id in collection.project_ids:
            if (
                get_project_access(
                    self._session,
                    project_id=project_id,
                    user_id=actor.id,
                )
                is None
            ):
                continue
            if (
                self._session.scalar(
                    select(ProjectPaper.document_id).where(
                        ProjectPaper.project_id == project_id,
                        ProjectPaper.document_id == document_id,
                    )
                )
                is not None
            ):
                return True
        return False

    def _document_is_accessible(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> bool:
        """Authorize by ID without hydrating the canonical Document text."""

        return (
            self._session.scalar(
                select(Document.id).where(
                    Document.id == document_id,
                    accessible_document_condition(user_id=actor.id),
                )
            )
            is not None
        )
