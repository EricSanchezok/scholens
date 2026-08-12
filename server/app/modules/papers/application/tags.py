"""Library-tag use cases shared by every transport."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagRenameRequest,
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor
from app.shared.application.operation_context import OperationContext


LIBRARY_TAG_CREATED = OperationAction("library.tag_created")
LIBRARY_TAG_RENAMED = OperationAction("library.tag_renamed")
LIBRARY_TAG_DELETED = OperationAction("library.tag_deleted")
LIBRARY_TAG_ASSIGNMENTS_REPLACED = OperationAction("library.tag_assignments_replaced")


class LibraryTagGateway(Protocol):
    def list(self, *, user_id: int) -> list[LibraryTagResponse]: ...

    def create(
        self,
        *,
        user_id: int,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse: ...

    def rename(
        self,
        *,
        user_id: int,
        tag_id: UUID,
        request: LibraryTagRenameRequest,
    ) -> LibraryTagResponse: ...

    def delete(self, *, user_id: int, tag_id: UUID) -> None: ...

    def replace_assignments(
        self,
        *,
        user_id: int,
        request: LibraryTagAssignmentRequest,
    ) -> int: ...


class LibraryTags:
    def __init__(
        self,
        gateway: LibraryTagGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def list(self, *, actor: Actor) -> LibraryTagListResponse:
        return LibraryTagListResponse(items=self._gateway.list(user_id=actor.id))

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse:
        result = self._gateway.create(user_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_TAG_CREATED,
            resources=(ResourceRef(type="library_tag", id=str(result.id)),),
        )
        return result

    def rename(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        tag_id: UUID,
        request: LibraryTagRenameRequest,
    ) -> LibraryTagResponse:
        result = self._gateway.rename(
            user_id=actor.id,
            tag_id=tag_id,
            request=request,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_TAG_RENAMED,
            resources=(ResourceRef(type="library_tag", id=str(result.id)),),
        )
        return result

    def delete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        tag_id: UUID,
    ) -> None:
        self._gateway.delete(user_id=actor.id, tag_id=tag_id)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_TAG_DELETED,
            resources=(ResourceRef(type="library_tag", id=str(tag_id)),),
        )

    def replace_assignments(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: LibraryTagAssignmentRequest,
    ) -> LibraryTagAssignmentResponse:
        updated_paper_count = self._gateway.replace_assignments(
            user_id=actor.id,
            request=request,
        )
        if updated_paper_count:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_TAG_ASSIGNMENTS_REPLACED,
                resources=(ResourceRef(type="library", id=str(actor.id)),),
            )
        return LibraryTagAssignmentResponse(updated_paper_count=updated_paper_count)
