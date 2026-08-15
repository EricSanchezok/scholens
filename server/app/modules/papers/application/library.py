"""Personal Library and public-share use cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from collections.abc import Mapping, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.documents import (
    CollectPublicPaperResponse,
    DocumentResponse,
    LibraryPaperListResponse,
    LibraryPaperListEntry,
    LibraryOutputListResponse,
    LibraryOutputResponse,
    LibraryOutputSort,
    LibraryPaperRemovalResponse,
    LibraryPaperResponse,
    LibraryPaperSort,
    LibrarySummaryResponse,
    LibraryPaperShareResponse,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
    PublicPaperResponse,
)
from app.modules.papers.application.downloads import PaperDownloadSigner
from app.modules.papers.application.actions import (
    LIBRARY_PAPER_COLLECTED,
    LIBRARY_PAPER_REMOVED,
    LIBRARY_PAPER_SHARED,
    LIBRARY_PAPER_UNSHARED,
    LIBRARY_PAPER_UPDATED,
)
from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor
from app.shared.application import SignedCursorCodec
from app.shared.application.operation_context import OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind


class LibraryPageDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True, slots=True)
class LibraryPagePosition:
    key: str
    id: UUID


@dataclass(frozen=True, slots=True)
class LibraryPaperPage:
    items: list[LibraryPaperListEntry]
    positions: list[LibraryPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class LibraryOutputPage:
    items: list[LibraryOutputResponse]
    positions: list[LibraryPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class PublicShare:
    document_id: UUID
    storage_key: str
    document: DocumentResponse
    owner: PublicPaperOwnerResponse


@dataclass(frozen=True, slots=True)
class LibraryPaperUpdateResult:
    response: LibraryPaperResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperAttachment:
    library_entry_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperRemoval:
    created_gc_job_id: UUID | None


class PaperLibraryGateway(Protocol):
    def list(
        self,
        *,
        user_id: int,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        sort: LibraryPaperSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryPaperPage: ...

    def paper_count(self, *, user_id: int) -> int: ...

    def ingestion_counts(self, *, user_id: int) -> tuple[int, int]: ...

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse: ...

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperUpdateResult: ...

    def share(self, *, user_id: int, document_id: UUID) -> str: ...

    def unshare(self, *, user_id: int, document_id: UUID) -> bool: ...

    def remove(
        self,
        *,
        user_id: int,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> LibraryPaperRemoval: ...

    def remove_many(
        self,
        *,
        user_id: int,
        document_ids: tuple[UUID, ...],
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> dict[UUID, LibraryPaperRemoval]: ...

    def public_share(self, *, share_token: str) -> PublicShare: ...

    def find_entry_id(self, *, user_id: int, document_id: UUID) -> UUID | None: ...

    def attach(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> LibraryPaperAttachment: ...


class LibraryOutputsGateway(Protocol):
    def list(
        self,
        *,
        user_id: int,
        query: str | None,
        kinds: tuple[ResearchItemKind, ...],
        sort: LibraryOutputSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryOutputPage: ...

    def count(self, *, user_id: int) -> int: ...


class LibraryCapacity(Protocol):
    def require(self, *, actor: Actor, document_id: UUID) -> None: ...


class PaperLibrary:
    def __init__(
        self,
        *,
        gateway: PaperLibraryGateway,
        outputs: LibraryOutputsGateway,
        capacity: LibraryCapacity,
        signer: PaperDownloadSigner,
        cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._outputs = outputs
        self._capacity = capacity
        self._signer = signer
        self._cursors = cursors
        self._journal = journal

    def list(
        self,
        *,
        actor: Actor,
        query: str | None = None,
        tag_ids: tuple[UUID, ...] = (),
        sort: LibraryPaperSort = LibraryPaperSort.ADDED_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LibraryPaperListResponse:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_tags = tuple(sorted(set(tag_ids), key=str))
        direction, position = self._decode_cursor(
            actor=actor,
            collection="papers",
            filters={
                "q": normalized_query,
                "tag_ids": [str(tag_id) for tag_id in normalized_tags],
                "sort": sort.value,
                "limit": limit,
            },
            cursor=cursor,
        )
        page = self._gateway.list(
            user_id=actor.id,
            query=normalized_query,
            tag_ids=normalized_tags,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        return LibraryPaperListResponse(
            items=page.items,
            previous_cursor=self._previous_cursor(
                actor=actor,
                collection="papers",
                filters={
                    "q": normalized_query,
                    "tag_ids": [str(tag_id) for tag_id in normalized_tags],
                    "sort": sort.value,
                    "limit": limit,
                },
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            next_cursor=self._next_cursor(
                actor=actor,
                collection="papers",
                filters={
                    "q": normalized_query,
                    "tag_ids": [str(tag_id) for tag_id in normalized_tags],
                    "sort": sort.value,
                    "limit": limit,
                },
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            total_count=page.total_count,
        )

    def list_outputs(
        self,
        *,
        actor: Actor,
        query: str | None = None,
        kinds: tuple[ResearchItemKind, ...] = (),
        sort: LibraryOutputSort = LibraryOutputSort.UPDATED_DESC,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LibraryOutputListResponse:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_kinds = tuple(sorted(set(kinds), key=lambda value: value.value))
        filters = {
            "q": normalized_query,
            "kinds": [kind.value for kind in normalized_kinds],
            "sort": sort.value,
            "limit": limit,
        }
        direction, position = self._decode_cursor(
            actor=actor,
            collection="outputs",
            filters=filters,
            cursor=cursor,
        )
        page = self._outputs.list(
            user_id=actor.id,
            query=normalized_query,
            kinds=normalized_kinds,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        return LibraryOutputListResponse(
            items=page.items,
            previous_cursor=self._previous_cursor(
                actor=actor,
                collection="outputs",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            next_cursor=self._next_cursor(
                actor=actor,
                collection="outputs",
                filters=filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            total_count=page.total_count,
        )

    def summary(self, *, actor: Actor) -> LibrarySummaryResponse:
        ingestion_count, attention_count = self._gateway.ingestion_counts(
            user_id=actor.id
        )
        return LibrarySummaryResponse(
            paper_count=self._gateway.paper_count(user_id=actor.id),
            ingestion_count=ingestion_count,
            attention_count=attention_count,
            output_count=self._outputs.count(user_id=actor.id),
        )

    def get(self, *, actor: Actor, document_id: UUID) -> LibraryPaperResponse:
        return self._gateway.get(user_id=actor.id, document_id=document_id)

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperResponse:
        result = self._gateway.update(
            user_id=actor.id,
            document_id=document_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_UPDATED,
                resources=(
                    ResourceRef(type="document", id=str(document_id)),
                    ResourceRef(
                        type="library_paper",
                        id=str(result.response.library_entry_id),
                    ),
                ),
            )
        return result.response

    def share(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> LibraryPaperShareResponse:
        share_token = self._gateway.share(
            user_id=actor.id,
            document_id=document_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_PAPER_SHARED,
            resources=(ResourceRef(type="document", id=str(document_id)),),
        )
        return LibraryPaperShareResponse(
            share_token=share_token,
            is_public=True,
        )

    def unshare(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> None:
        changed = self._gateway.unshare(
            user_id=actor.id,
            document_id=document_id,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_UNSHARED,
                resources=(ResourceRef(type="document", id=str(document_id)),),
            )

    def remove(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> None:
        result = self._gateway.remove(
            user_id=actor.id,
            document_id=document_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes = [
            OperationChange(
                action=LIBRARY_PAPER_REMOVED,
                resources=(ResourceRef(type="document", id=str(document_id)),),
            )
        ]
        if result.created_gc_job_id is not None:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(
                        ResourceRef(type="job", id=str(result.created_gc_job_id)),
                    ),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )

    def remove_many(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_ids: Sequence[UUID],
    ) -> LibraryPaperRemovalResponse:
        unique_ids: tuple[UUID, ...] = tuple(dict.fromkeys(document_ids))
        results = self._gateway.remove_many(
            user_id=actor.id,
            document_ids=unique_ids,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes: list[OperationChange] = []
        for document_id, result in results.items():
            changes.append(
                OperationChange(
                    action=LIBRARY_PAPER_REMOVED,
                    resources=(ResourceRef("document", str(document_id)),),
                )
            )
            if result.created_gc_job_id is not None:
                changes.append(
                    OperationChange(
                        action=JOB_CREATED,
                        resources=(ResourceRef("job", str(result.created_gc_job_id)),),
                    )
                )
        self._journal.append_many(actor=actor, operation=operation, changes=changes)
        return LibraryPaperRemovalResponse(
            removed_document_ids=list(results),
        )

    def _decode_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        cursor: str | None,
    ) -> tuple[LibraryPageDirection, LibraryPagePosition | None]:
        if cursor is None:
            return LibraryPageDirection.FORWARD, None
        try:
            direction, key, item_id = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(actor, collection, filters),
                arity=3,
            )
            return (
                LibraryPageDirection(direction),
                LibraryPagePosition(key=key, id=UUID(item_id)),
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="library_cursor_invalid",
                message="The Library cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _encode_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        direction: LibraryPageDirection,
        position: LibraryPagePosition,
    ) -> str:
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(actor, collection, filters),
            values=(direction.value, position.key, str(position.id)),
        )

    def _previous_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        page: LibraryPaperPage | LibraryOutputPage,
        direction: LibraryPageDirection,
        had_position: bool,
    ) -> str | None:
        if not page.positions:
            return None
        has_previous = (
            page.has_more
            if direction is LibraryPageDirection.BACKWARD
            else had_position
        )
        if not has_previous:
            return None
        return self._encode_cursor(
            actor=actor,
            collection=collection,
            filters=filters,
            direction=LibraryPageDirection.BACKWARD,
            position=page.positions[0],
        )

    def _next_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        page: LibraryPaperPage | LibraryOutputPage,
        direction: LibraryPageDirection,
        had_position: bool,
    ) -> str | None:
        if not page.positions:
            return None
        has_next = (
            page.has_more if direction is LibraryPageDirection.FORWARD else had_position
        )
        if not has_next:
            return None
        return self._encode_cursor(
            actor=actor,
            collection=collection,
            filters=filters,
            direction=LibraryPageDirection.FORWARD,
            position=page.positions[-1],
        )

    @staticmethod
    def _cursor_binding(
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
    ) -> str:
        return json.dumps(
            {
                "revision": "library-v1",
                "user_id": actor.id,
                "collection": collection,
                "filters": filters,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def get_public(self, *, share_token: str) -> PublicPaperResponse:
        shared = self._gateway.public_share(share_token=share_token)
        try:
            file_url = self._signer.sign(storage_key=shared.storage_key)
        except RuntimeError as exc:
            raise AppError(
                code="document_file_url_unavailable",
                message="The document file is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        return PublicPaperResponse(
            document=shared.document,
            file_url=file_url,
            owner=shared.owner,
        )

    def collect_public(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        share_token: str,
    ) -> CollectPublicPaperResponse:
        shared = self._gateway.public_share(share_token=share_token)
        existing_id = self._gateway.find_entry_id(
            user_id=actor.id,
            document_id=shared.document_id,
        )
        if existing_id is not None:
            return CollectPublicPaperResponse(
                document_id=shared.document_id,
                library_entry_id=existing_id,
                already_exists=True,
            )
        self._capacity.require(actor=actor, document_id=shared.document_id)
        attached = self._gateway.attach(
            user_id=actor.id,
            document_id=shared.document_id,
        )
        if attached.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_COLLECTED,
                resources=(
                    ResourceRef(type="document", id=str(shared.document_id)),
                    ResourceRef(
                        type="library_paper",
                        id=str(attached.library_entry_id),
                    ),
                ),
            )
        return CollectPublicPaperResponse(
            document_id=shared.document_id,
            library_entry_id=attached.library_entry_id,
            already_exists=not attached.created,
        )
