"""Logical paper and storage usage billed to a Scholens account."""

from __future__ import annotations

from uuid import UUID

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    LibraryPaper,
    Project,
    ProjectPaper,
)
from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery


class ResourceUsageRepository:
    @staticmethod
    def _completed_document_ids(
        *,
        user_id: int,
        include_project_id: UUID | None = None,
        exclude_project_id: UUID | None = None,
    ) -> Subquery:
        library_ids = (
            select(LibraryPaper.document_id.label("document_id"))
            .join(Document, Document.id == LibraryPaper.document_id)
            .where(
                LibraryPaper.user_id == user_id,
                Document.processing_status == DocumentProcessingStatus.COMPLETED.value,
            )
        )
        project_owner_filter = Project.owner_id == user_id
        if include_project_id is not None:
            project_owner_filter = or_(
                project_owner_filter,
                Project.id == include_project_id,
            )
        if exclude_project_id is not None:
            project_owner_filter = project_owner_filter & (
                Project.id != exclude_project_id
            )
        project_ids = (
            select(ProjectPaper.document_id.label("document_id"))
            .join(Document, Document.id == ProjectPaper.document_id)
            .join(Project, Project.id == ProjectPaper.project_id)
            .where(
                project_owner_filter,
                Document.processing_status == DocumentProcessingStatus.COMPLETED.value,
            )
        )
        return union(library_ids, project_ids).subquery()

    def completed_documents(
        self,
        db: Session,
        *,
        user_id: int,
        include_project_id: UUID | None = None,
        exclude_project_id: UUID | None = None,
    ) -> list[Document]:
        """Return the unique completed-document view for a prospective owner."""
        document_ids = self._completed_document_ids(
            user_id=user_id,
            include_project_id=include_project_id,
            exclude_project_id=exclude_project_id,
        )
        return list(
            db.scalars(
                select(Document).join(
                    document_ids,
                    document_ids.c.document_id == Document.id,
                )
            ).all()
        )

    def completed_reference_count(self, db: Session, *, user_id: int) -> int:
        document_ids = self._completed_document_ids(user_id=user_id)
        return int(db.scalar(select(func.count()).select_from(document_ids)) or 0)

    def completed_storage_kb(self, db: Session, *, user_id: int) -> int:
        document_ids = self._completed_document_ids(user_id=user_id)
        total_bytes = int(
            db.scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0)).join(
                    document_ids, document_ids.c.document_id == Document.id
                )
            )
            or 0
        )
        return (total_bytes + 1023) // 1024

    def owned_document_ids(self, db: Session, *, user_id: int) -> set[object]:
        document_ids = self._completed_document_ids(user_id=user_id)
        return set(db.scalars(select(document_ids.c.document_id)).all())

    def contains_document(
        self,
        db: Session,
        *,
        user_id: int,
        document_id: object,
    ) -> bool:
        document_ids = self._completed_document_ids(user_id=user_id)
        return bool(
            db.scalar(
                select(func.count())
                .select_from(document_ids)
                .where(document_ids.c.document_id == document_id)
            )
        )


resource_usage_repository = ResourceUsageRepository()
