"""SQLAlchemy adapter for Library tag application use cases."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagCreateRequest,
    LibraryTagRenameRequest,
    LibraryTagResponse,
)
from app.modules.papers.application.tags import (
    LibraryTagPage,
    LibraryTagPagePosition,
)
from app.modules.papers.infrastructure.tag_repository import library_tag_repository
from sqlalchemy.orm import Session


class SqlAlchemyLibraryTagGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _response(tag: object) -> LibraryTagResponse:
        from app.modules.papers.infrastructure.models import PaperTag

        if not isinstance(tag, PaperTag):
            raise TypeError("expected PaperTag")
        return LibraryTagResponse(id=tag.id, name=tag.name, color=tag.color)

    def list(self, *, user_id: int) -> list[LibraryTagResponse]:
        return [
            self._response(tag)
            for tag in library_tag_repository.list_owned(self._db, user_id=user_id)
        ]

    def list_page(
        self,
        *,
        user_id: int,
        limit: int,
        position: LibraryTagPagePosition | None,
    ) -> LibraryTagPage:
        rows = library_tag_repository.list_owned_page(
            self._db,
            user_id=user_id,
            limit=limit,
            position_name=position.name if position is not None else None,
            position_id=position.id if position is not None else None,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        return LibraryTagPage(
            items=[self._response(row.tag) for row in rows],
            positions=[
                LibraryTagPagePosition(name=row.sort_name, id=row.tag.id)
                for row in rows
            ],
            has_more=has_more,
        )

    def get(self, *, user_id: int, tag_id: UUID) -> LibraryTagResponse | None:
        tag = library_tag_repository.get_owned(
            self._db,
            user_id=user_id,
            tag_id=tag_id,
        )
        return self._response(tag) if tag is not None else None

    def create(
        self,
        *,
        user_id: int,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse:
        return self._response(
            library_tag_repository.create(
                self._db,
                user_id=user_id,
                name=request.name,
                color=request.color,
            )
        )

    def rename(
        self,
        *,
        user_id: int,
        tag_id: UUID,
        request: LibraryTagRenameRequest,
    ) -> LibraryTagResponse:
        return self._response(
            library_tag_repository.rename(
                self._db,
                user_id=user_id,
                tag_id=tag_id,
                name=request.name,
            )
        )

    def delete(self, *, user_id: int, tag_id: UUID) -> None:
        library_tag_repository.delete_owned(
            self._db,
            user_id=user_id,
            tag_id=tag_id,
        )

    def replace_assignments(
        self,
        *,
        user_id: int,
        request: LibraryTagAssignmentRequest,
    ) -> int:
        return library_tag_repository.replace_assignments(
            self._db,
            user_id=user_id,
            document_ids=request.document_ids,
            tag_ids=request.tag_ids,
        )
