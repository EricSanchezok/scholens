"""Library-tag use cases shared by every transport."""

from __future__ import annotations

from dataclasses import dataclass
import json
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
from app.shared.application import Actor, SignedCursorCodec
from app.shared.application.operation_context import OperationContext
from app.shared.domain import AppError, FailureKind


LIBRARY_TAG_CREATED = OperationAction("library.tag_created")
LIBRARY_TAG_RENAMED = OperationAction("library.tag_renamed")
LIBRARY_TAG_DELETED = OperationAction("library.tag_deleted")
LIBRARY_TAG_ASSIGNMENTS_REPLACED = OperationAction("library.tag_assignments_replaced")


@dataclass(frozen=True, slots=True)
class LibraryTagPagePosition:
    name: str
    id: UUID


@dataclass(frozen=True, slots=True)
class LibraryTagPage:
    items: list[LibraryTagResponse]
    positions: list[LibraryTagPagePosition]
    has_more: bool


class LibraryTagGateway(Protocol):
    def list(self, *, user_id: int) -> list[LibraryTagResponse]: ...

    def list_page(
        self,
        *,
        user_id: int,
        limit: int,
        position: LibraryTagPagePosition | None,
    ) -> LibraryTagPage: ...

    def get(self, *, user_id: int, tag_id: UUID) -> LibraryTagResponse | None: ...

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
        cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._cursors = cursors
        self._journal = journal

    def list(self, *, actor: Actor) -> LibraryTagListResponse:
        return LibraryTagListResponse(items=self._gateway.list(user_id=actor.id))

    def list_page(
        self,
        *,
        actor: Actor,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LibraryTagListResponse:
        position = self._decode_cursor(actor=actor, cursor=cursor)
        page = self._gateway.list_page(
            user_id=actor.id,
            limit=limit,
            position=position,
        )
        return LibraryTagListResponse(
            items=page.items,
            next_cursor=self._page_cursor(actor=actor, page=page),
        )

    def get(self, *, actor: Actor, tag_id: UUID) -> LibraryTagResponse | None:
        return self._gateway.get(user_id=actor.id, tag_id=tag_id)

    def _decode_cursor(
        self,
        *,
        actor: Actor,
        cursor: str | None,
    ) -> LibraryTagPagePosition | None:
        if cursor is None:
            return None
        try:
            name, tag_id = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(actor),
                arity=2,
            )
            return LibraryTagPagePosition(name=name, id=UUID(tag_id))
        except (TypeError, ValueError) as error:
            raise AppError(
                code="library_tag_cursor_invalid",
                message="The Library tag cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _page_cursor(self, *, actor: Actor, page: LibraryTagPage) -> str | None:
        if not page.has_more or not page.positions:
            return None
        position = page.positions[-1]
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(actor),
            values=(position.name, str(position.id)),
        )

    @staticmethod
    def _cursor_binding(actor: Actor) -> str:
        return json.dumps(
            {
                "revision": "library-tags-v1",
                "user_id": actor.id,
                "collection": "library-tags",
            },
            separators=(",", ":"),
            sort_keys=True,
        )

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
