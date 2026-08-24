"""Personal Library and public-share use cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol
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
from app.shared.domain.enums import PaperStatus
from pydantic import BaseModel, ConfigDict, Field


class LibraryPageDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True, slots=True)
class LibraryPagePosition:
    key: str
    id: UUID
    kind: Literal["ingestion", "paper"] = "paper"


@dataclass(frozen=True, slots=True)
class LibraryPaperPage:
    items: list[LibraryPaperListEntry]
    positions: list[LibraryPagePosition]
    has_more: bool
    total_count: int


@dataclass(frozen=True, slots=True)
class LibraryPaperSummaryPage:
    """Durable Library rows projected to bounded scalar metadata in SQL."""

    items: list[LibraryPaperListEntry]
    positions: list[LibraryPagePosition]
    has_more: bool
    total_count: int
    content_truncated: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperSummaryList:
    value: LibraryPaperListResponse
    content_truncated: bool


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
    content_truncated: bool = False


@dataclass(frozen=True, slots=True)
class LibraryPaperAttachment:
    library_entry_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperPageAccess:
    library_entry_id: UUID
    document_id: UUID
    revision: str
    access_url: str | None
    durable_json_utf8_upper_bound: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryPaperRemoval:
    created_gc_job_id: UUID | None


class LibraryPaperConfirmationState(BaseModel):
    """Stable sharing fields that deliberately exclude signed presentation URLs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    library_entry_id: UUID
    document_id: UUID
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_title: str
    is_public: bool
    share_token_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class LibraryPaperConfirmationPlan:
    state: LibraryPaperConfirmationState


class LibraryPaperRemovalItemState(LibraryPaperConfirmationState):
    personal_annotation_thread_count: int = Field(ge=0)
    personal_annotation_comment_count: int = Field(ge=0)
    personal_annotation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LibraryPaperRemovalState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[LibraryPaperRemovalItemState, ...]


@dataclass(frozen=True, slots=True)
class LibraryPaperRemovalPlan:
    state: LibraryPaperRemovalState


class PaperLibraryGateway(Protocol):
    def list(
        self,
        *,
        user_id: int,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        statuses: tuple[PaperStatus, ...] = (),
        sort: LibraryPaperSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
        include_active_ingestions: bool = True,
        maximum_retained_bytes: int | None = None,
    ) -> LibraryPaperPage: ...

    def list_summaries(
        self,
        *,
        user_id: int,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        statuses: tuple[PaperStatus, ...],
        sort: LibraryPaperSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryPaperSummaryPage: ...

    def paper_count(self, *, user_id: int) -> int: ...

    def ingestion_counts(self, *, user_id: int) -> tuple[int, int]: ...

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse: ...

    def get_revision(
        self, *, user_id: int, document_id: UUID
    ) -> LibraryPaperPageAccess: ...

    def get_retained_size(
        self, *, user_id: int, document_id: UUID
    ) -> LibraryPaperPageAccess: ...

    def confirmation_plan(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> LibraryPaperConfirmationPlan: ...

    def removal_plan(
        self,
        *,
        user_id: int,
        document_ids: tuple[UUID, ...],
    ) -> LibraryPaperRemovalPlan: ...

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperUpdateResult: ...

    def update_summary(
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

    def resolve_public_document_id(self, *, share_token: str) -> UUID: ...

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
        maximum_payload_json_bytes: int | None = None,
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
        statuses: tuple[PaperStatus, ...] = (),
        sort: LibraryPaperSort = LibraryPaperSort.ADDED_DESC,
        cursor: str | None = None,
        limit: int = 20,
        include_active_ingestions: bool = True,
        maximum_retained_bytes: int | None = None,
    ) -> LibraryPaperListResponse:
        (
            normalized_query,
            normalized_tags,
            normalized_statuses,
            cursor_filters,
            direction,
            position,
        ) = self._paper_list_request(
            actor=actor,
            query=query,
            tag_ids=tag_ids,
            statuses=statuses,
            sort=sort,
            include_active_ingestions=include_active_ingestions,
            cursor=cursor,
        )
        page = self._gateway.list(
            user_id=actor.id,
            query=normalized_query,
            tag_ids=normalized_tags,
            statuses=normalized_statuses,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
            include_active_ingestions=include_active_ingestions,
            maximum_retained_bytes=maximum_retained_bytes,
        )
        return LibraryPaperListResponse(
            items=page.items,
            previous_cursor=self._previous_cursor(
                actor=actor,
                collection="papers",
                filters=cursor_filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            next_cursor=self._next_cursor(
                actor=actor,
                collection="papers",
                filters=cursor_filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            total_count=page.total_count,
        )

    def list_summaries(
        self,
        *,
        actor: Actor,
        query: str | None = None,
        tag_ids: tuple[UUID, ...] = (),
        statuses: tuple[PaperStatus, ...] = (),
        sort: LibraryPaperSort = LibraryPaperSort.ADDED_DESC,
        cursor: str | None = None,
        limit: int = 5,
    ) -> LibraryPaperSummaryList:
        """Return a durable, cursor-compatible Library summary page."""

        (
            normalized_query,
            normalized_tags,
            normalized_statuses,
            cursor_filters,
            direction,
            position,
        ) = self._paper_list_request(
            actor=actor,
            query=query,
            tag_ids=tag_ids,
            statuses=statuses,
            sort=sort,
            include_active_ingestions=False,
            cursor=cursor,
        )
        page = self._gateway.list_summaries(
            user_id=actor.id,
            query=normalized_query,
            tag_ids=normalized_tags,
            statuses=normalized_statuses,
            sort=sort,
            limit=limit,
            direction=direction,
            position=position,
        )
        value = LibraryPaperListResponse(
            items=page.items,
            previous_cursor=self._previous_cursor(
                actor=actor,
                collection="papers",
                filters=cursor_filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            next_cursor=self._next_cursor(
                actor=actor,
                collection="papers",
                filters=cursor_filters,
                page=page,
                direction=direction,
                had_position=position is not None,
            ),
            total_count=page.total_count,
        )
        return LibraryPaperSummaryList(
            value=value,
            content_truncated=page.content_truncated,
        )

    def _paper_list_request(
        self,
        *,
        actor: Actor,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        statuses: tuple[PaperStatus, ...],
        sort: LibraryPaperSort,
        include_active_ingestions: bool,
        cursor: str | None,
    ) -> tuple[
        str | None,
        tuple[UUID, ...],
        tuple[PaperStatus, ...],
        dict[str, object],
        LibraryPageDirection,
        LibraryPagePosition | None,
    ]:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_tags = tuple(sorted(set(tag_ids), key=str))
        normalized_statuses = tuple(
            sorted(set(statuses), key=lambda value: value.value)
        )
        cursor_filters: dict[str, object] = {
            "q": normalized_query,
            "tag_ids": [str(tag_id) for tag_id in normalized_tags],
            "statuses": [status.value for status in normalized_statuses],
            "sort": sort.value,
        }
        if not include_active_ingestions:
            cursor_filters["entry_scope"] = "durable_papers"
        direction, position = self._decode_cursor(
            actor=actor,
            collection="papers",
            filters=cursor_filters,
            cursor=cursor,
        )
        return (
            normalized_query,
            normalized_tags,
            normalized_statuses,
            cursor_filters,
            direction,
            position,
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
        maximum_payload_json_bytes: int | None = None,
    ) -> LibraryOutputListResponse:
        normalized_query = query.strip() if query and query.strip() else None
        normalized_kinds = tuple(sorted(set(kinds), key=lambda value: value.value))
        filters = {
            "q": normalized_query,
            "kinds": [kind.value for kind in normalized_kinds],
            "sort": sort.value,
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
            maximum_payload_json_bytes=maximum_payload_json_bytes,
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

    def authorize_revision(
        self, *, actor: Actor, document_id: UUID
    ) -> LibraryPaperPageAccess:
        return self._gateway.get_revision(
            user_id=actor.id,
            document_id=document_id,
        )

    def authorize_retained_size(
        self, *, actor: Actor, document_id: UUID
    ) -> LibraryPaperPageAccess:
        return self._gateway.get_retained_size(
            user_id=actor.id,
            document_id=document_id,
        )

    def confirmation_plan(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> LibraryPaperConfirmationPlan:
        return self._gateway.confirmation_plan(
            user_id=actor.id,
            document_id=document_id,
        )

    def removal_plan(
        self,
        *,
        actor: Actor,
        document_ids: Sequence[UUID],
    ) -> LibraryPaperRemovalPlan:
        return self._gateway.removal_plan(
            user_id=actor.id,
            document_ids=tuple(document_ids),
        )

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
            self._record_update(
                actor=actor,
                operation=operation,
                document_id=document_id,
                library_entry_id=result.response.library_entry_id,
            )
        return result.response

    def update_summary(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperUpdateResult:
        """Update a Library row and return the SQL-bounded MCP projection."""

        result = self._gateway.update_summary(
            user_id=actor.id,
            document_id=document_id,
            request=request,
        )
        if result.changed:
            self._record_update(
                actor=actor,
                operation=operation,
                document_id=document_id,
                library_entry_id=result.response.library_entry_id,
            )
        return result

    def _record_update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        library_entry_id: UUID,
    ) -> None:
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_PAPER_UPDATED,
            resources=(
                ResourceRef(type="document", id=str(document_id)),
                ResourceRef(type="library_paper", id=str(library_entry_id)),
            ),
        )

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
            try:
                direction, kind, key, item_id = self._cursors.decode_keyset(
                    cursor=cursor,
                    fingerprint=self._cursor_binding(actor, collection, filters),
                    arity=4,
                )
            except AppError as current_error:
                try:
                    direction, key, item_id = self._cursors.decode_keyset(
                        cursor=cursor,
                        fingerprint=self._cursor_binding(actor, collection, filters),
                        arity=3,
                    )
                except AppError:
                    raise current_error
                kind = "paper"
            if kind not in {"ingestion", "paper"}:
                raise ValueError("unknown Library page position kind")
            position_kind: Literal["ingestion", "paper"] = (
                "ingestion" if kind == "ingestion" else "paper"
            )
            return (
                LibraryPageDirection(direction),
                LibraryPagePosition(key=key, id=UUID(item_id), kind=position_kind),
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
            values=(
                direction.value,
                position.kind,
                position.key,
                str(position.id),
            ),
        )

    def _previous_cursor(
        self,
        *,
        actor: Actor,
        collection: str,
        filters: Mapping[str, object],
        page: LibraryPaperPage | LibraryPaperSummaryPage | LibraryOutputPage,
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
        page: LibraryPaperPage | LibraryPaperSummaryPage | LibraryOutputPage,
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
        document_id = self._gateway.resolve_public_document_id(share_token=share_token)
        existing_id = self._gateway.find_entry_id(
            user_id=actor.id,
            document_id=document_id,
        )
        if existing_id is not None:
            return CollectPublicPaperResponse(
                document_id=document_id,
                library_entry_id=existing_id,
                already_exists=True,
            )
        self._capacity.require(actor=actor, document_id=document_id)
        attached = self._gateway.attach(
            user_id=actor.id,
            document_id=document_id,
        )
        if attached.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_COLLECTED,
                resources=(
                    ResourceRef(type="document", id=str(document_id)),
                    ResourceRef(
                        type="library_paper",
                        id=str(attached.library_entry_id),
                    ),
                ),
            )
        return CollectPublicPaperResponse(
            document_id=document_id,
            library_entry_id=attached.library_entry_id,
            already_exists=not attached.created,
        )
