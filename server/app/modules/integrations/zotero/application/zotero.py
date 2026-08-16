"""Zotero connection, import, and synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroConnectionStatus,
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportRequest,
    ZoteroLibraryPage,
    ZoteroOperation,
    ZoteroOperationCounts,
    ZoteroOperationItem,
    ZoteroOperationProgress,
    ZoteroSyncPreferencesRequest,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.actions import (
    ZOTERO_ANNOTATIONS_SYNCED,
    ZOTERO_CONNECTION_CONNECTED,
    ZOTERO_CONNECTION_DISCONNECTED,
    ZOTERO_IMPORT_COMPLETED,
    ZOTERO_IMPORT_FAILED,
    ZOTERO_IMPORT_STARTED,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    ResourceRef,
)
from app.modules.jobs.application.actions import JOB_COMPLETED, JOB_CREATED, JOB_FAILED
from app.modules.jobs.application.contracts import JobResponse
from app.modules.jobs.application.jobs import (
    EnqueueJobCommand,
    IdempotentOperationPort,
    JobQueryPort,
    JobCommandPort,
    OperationClaim,
)
from app.modules.integrations.zotero.domain import (
    import_idempotency_key,
    require_zotero_connected,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, JobStatus
from scholens_job_contracts import JobQueue
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ZoteroGateway(Protocol):
    def save_oauth_request(
        self,
        *,
        user_id: int,
        request_token: ZoteroRequestToken,
        return_path: str,
        intent: str,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> None: ...

    def consume_oauth_callback(
        self,
        *,
        oauth_token: str,
    ) -> PreparedZoteroCallback | None: ...

    def save_connection(
        self,
        *,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> ZoteroConnectionChange: ...

    def status(self, *, actor: Actor) -> ZoteroConnectionStatus: ...

    def set_sync_preferences(
        self,
        *,
        actor: Actor,
        request: ZoteroSyncPreferencesRequest,
        library_version: int | None,
    ) -> ZoteroConnectionStatus: ...

    def disconnect(self, *, user_id: int) -> UUID | None: ...

    def credentials(
        self,
        *,
        user_id: int,
        lock: bool = False,
    ) -> ZoteroCredentials | None: ...

    def credential_revision_is_current(
        self,
        *,
        user_id: int,
        revision: UUID,
    ) -> bool: ...

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryPage: ...

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
        credential_revision: UUID,
    ) -> ZoteroImportPlan: ...

    def reserve_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID,
        credential_revision: UUID,
    ) -> UUID: ...

    def fail_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
        credential_revision: UUID,
    ) -> ZoteroItemMutation: ...

    def complete_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        upload_job_id: UUID,
        document_id: UUID,
        reused_document: bool,
        page_dimensions: PageDimensions,
        credential_revision: UUID,
    ) -> ZoteroImportMutation: ...

    def link_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
        credential_revision: UUID,
    ) -> ZoteroImportMutation: ...

    def sync_targets(
        self,
        *,
        user_id: int,
        limit: int,
        credential_revision: UUID,
    ) -> tuple[ZoteroSyncTarget, ...]: ...

    def apply_sync(
        self,
        *,
        actor: Actor,
        batch: ZoteroSyncBatch,
        credential_revision: UUID,
    ) -> ZoteroSyncMutation: ...

    def auto_import_cursor(self, *, user_id: int) -> ZoteroAutoImportCursor | None: ...

    def advance_sync_checkpoint(
        self,
        *,
        user_id: int,
        credential_revision: UUID,
        library_version: int | None,
        auto_import_cursor: ZoteroAutoImportCursor | None,
    ) -> bool: ...


class ZoteroImportCapacity(Protocol):
    def require(self, *, actor: Actor) -> None: ...


class ZoteroJobs(JobCommandPort, JobQueryPort, Protocol):
    def cancel(self, *, requested_by_id: int, job_id: UUID) -> JobResponse: ...

    def payload(
        self, *, requested_by_id: int, job_id: UUID
    ) -> dict[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class ZoteroCredentials:
    user_id: str
    api_key: str
    revision: UUID


@dataclass(frozen=True, slots=True)
class ZoteroRequestToken:
    token: str
    secret: str


@dataclass(frozen=True, slots=True)
class ZoteroAccessToken:
    user_id: str
    api_key: str


@dataclass(frozen=True, slots=True)
class ZoteroAutoImportCursor:
    library_version: int
    start: int = 0


type PageDimensions = tuple[tuple[int, float, float], ...]


@dataclass(frozen=True, slots=True)
class ZoteroItemSnapshot:
    item_key: str
    title: str
    authors: tuple[str, ...]
    abstract: str | None
    publish_date: str | None
    doi: str | None
    tags: tuple[str, ...]
    date_added: str | None
    item_type: str
    venue: str | None
    collection_keys: tuple[str, ...]
    has_pdf_attachment: bool
    has_resolvable_source: bool = False
    has_metadata: bool = True
    version: int | None = None


@dataclass(frozen=True, slots=True)
class ZoteroLibrarySnapshot:
    items: tuple[ZoteroItemSnapshot, ...]
    start: int = 0
    limit: int = 25
    total_count: int = 0
    library_version: int | None = None


@dataclass(frozen=True, slots=True)
class ZoteroCollectionSnapshot:
    key: str
    name: str


@dataclass(frozen=True, slots=True)
class ZoteroCollectionSnapshotPage:
    items: tuple[ZoteroCollectionSnapshot, ...]
    start: int
    limit: int
    total_count: int


@dataclass(frozen=True, slots=True)
class ZoteroAttachmentSnapshot:
    item_key: str
    import_source: str
    attachment_key: str | None
    source_url: str | None
    annotations_json: str
    version: int | None = None


@dataclass(frozen=True, slots=True)
class ZoteroImportContent:
    item: ZoteroItemSnapshot
    attachment: ZoteroAttachmentSnapshot
    pdf_content: bytes | None
    page_dimensions: PageDimensions
    error: str | None


@dataclass(frozen=True, slots=True)
class ZoteroImportPlanItem:
    item: ZoteroItemSnapshot
    disposition: Literal["import", "link_existing", "link_batch"]
    document_id: UUID | None = None
    document_source_key: str | None = None
    source_item_key: str | None = None


@dataclass(frozen=True, slots=True)
class ZoteroImportPlan:
    items: tuple[ZoteroImportPlanItem, ...]
    skipped_already_imported: int
    errors: tuple[ZoteroImportError, ...]
    skipped_item_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ZoteroItemMutation:
    imported_item_id: UUID
    changed: bool


@dataclass(frozen=True, slots=True)
class ZoteroImportMutation:
    imported_item_id: UUID
    result: ZoteroImportItemResult
    changed: bool
    completed: bool


@dataclass(frozen=True, slots=True)
class ZoteroSyncTarget:
    imported_item_id: UUID
    item_key: str
    document_id: UUID
    attachment_key: str
    document_source_key: str | None


@dataclass(frozen=True, slots=True)
class ZoteroSyncUpdate:
    target: ZoteroSyncTarget
    annotations_json: str
    page_dimensions: PageDimensions


@dataclass(frozen=True, slots=True)
class ZoteroSyncFailure:
    item_key: str
    error_code: str


@dataclass(frozen=True, slots=True)
class ZoteroSyncBatch:
    updates: tuple[ZoteroSyncUpdate, ...]
    failures: tuple[ZoteroSyncFailure, ...]


@dataclass(frozen=True, slots=True)
class ZoteroSyncMutation:
    response: ZoteroSyncResponse
    changed_document_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PreparedZoteroCallback:
    user_id: int
    request_token: ZoteroRequestToken
    expires_at: datetime
    correlation_id: UUID
    origin_operation_id: UUID
    return_path: str
    intent: str


@dataclass(frozen=True, slots=True)
class ZoteroConnectionChange:
    connection_revision: UUID
    changed: bool


class Zotero:
    def __init__(
        self,
        *,
        gateway: ZoteroGateway,
        capacity: ZoteroImportCapacity,
        idempotency: IdempotentOperationPort,
        jobs: ZoteroJobs,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._idempotency = idempotency
        self._jobs = jobs
        self._journal = journal

    def save_oauth_request(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request_token: ZoteroRequestToken,
        auth_url: str,
        return_path: str,
        intent: str,
    ) -> ZoteroConnectResponse:
        self._gateway.save_oauth_request(
            user_id=actor.id,
            request_token=request_token,
            return_path=return_path,
            intent=intent,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
        )
        return ZoteroConnectResponse(auth_url=auth_url)

    def consume_oauth_callback(
        self,
        *,
        oauth_token: str,
        now: datetime,
    ) -> PreparedZoteroCallback | None:
        del now
        callback = self._gateway.consume_oauth_callback(
            oauth_token=oauth_token,
        )
        return callback

    def complete_oauth_callback(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> bool:
        if actor.id != callback.user_id:
            raise AppError(
                code="zotero_callback_owner_mismatch",
                message="Zotero callback ownership could not be verified",
                kind=FailureKind.PERMISSION_DENIED,
            )
        change = self._gateway.save_connection(
            callback=callback,
            access_token=access_token,
        )
        if change.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_CONNECTION_CONNECTED,
                resources=(
                    ResourceRef(
                        "integration",
                        f"zotero:{change.connection_revision}",
                    ),
                ),
            )
        return True

    def status(self, *, actor: Actor) -> ZoteroConnectionStatus:
        response = self._gateway.status(actor=actor)
        active = next(
            (
                job
                for job in self._jobs.list(
                    requested_by_id=actor.id,
                    project_id=None,
                    document_id=None,
                    operation=None,
                    statuses=(JobStatus.PENDING, JobStatus.RUNNING),
                )
                if job.operation
                in {JobOperation.ZOTERO_IMPORT.value, JobOperation.ZOTERO_SYNC.value}
            ),
            None,
        )
        return response.model_copy(
            update={
                "active_operation_id": active.id if active else None,
                "active_operation_kind": (
                    "import"
                    if active and active.operation == JobOperation.ZOTERO_IMPORT.value
                    else "sync"
                    if active
                    else None
                ),
            }
        )

    def set_sync_preferences(
        self,
        *,
        actor: Actor,
        request: ZoteroSyncPreferencesRequest,
        library_version: int | None,
    ) -> ZoteroConnectionStatus:
        return self._gateway.set_sync_preferences(
            actor=actor,
            request=request,
            library_version=library_version,
        )

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> None:
        connection_id = self._gateway.disconnect(user_id=actor.id)
        if connection_id is not None:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_CONNECTION_DISCONNECTED,
                resources=(ResourceRef("zotero_connection", str(connection_id)),),
            )

    def prepare_library(self, *, actor: Actor) -> ZoteroCredentials:
        return self._require_credentials(actor)

    def job_credentials(self, *, user_id: int) -> ZoteroCredentials:
        credentials = self._gateway.credentials(user_id=user_id)
        require_zotero_connected(connected=credentials is not None)
        assert credentials is not None
        return credentials

    def credential_revision_is_current(
        self,
        *,
        user_id: int,
        revision: UUID,
    ) -> bool:
        return self._gateway.credential_revision_is_current(
            user_id=user_id,
            revision=revision,
        )

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryPage:
        return self._gateway.library(actor=actor, snapshot=snapshot)

    def enqueue_import(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ZoteroImportRequest,
        idempotency_key: str,
    ) -> ZoteroOperation:
        credentials = self._require_credentials(actor, lock=True)
        self._capacity.require(actor=actor)
        operation_key = import_idempotency_key(
            actor_id=actor.id,
            request_key=idempotency_key,
        )
        existing = self._jobs.find_by_idempotency_key(key=operation_key)
        if existing is not None:
            payload = self._jobs.payload(
                requested_by_id=actor.id,
                job_id=existing.id,
            )
            if payload.get("item_keys") != list(request.item_keys):
                raise AppError(
                    code="idempotency_key_reused",
                    message="The idempotency key was already used for another request",
                    kind=FailureKind.CONFLICT,
                )
            return _operation_response(existing, kind="import", payload=payload)
        self._require_no_active_operation(actor=actor)
        job_id = uuid4()
        enqueued = self._jobs.enqueue(
            command=EnqueueJobCommand(
                job_id=job_id,
                operation=JobOperation.ZOTERO_IMPORT,
                requested_by_id=actor.id,
                correlation_id=operation.trace.correlation_id,
                origin_operation_id=operation.trace.operation_id,
                idempotency_key=operation_key,
                payload={
                    "item_keys": list(request.item_keys),
                    "credential_revision": str(credentials.revision),
                },
                task_name="import_zotero_items",
                queue=JobQueue.MAINTENANCE,
            )
        )
        if not enqueued.created and enqueued.payload.get("item_keys") != list(
            request.item_keys
        ):
            raise AppError(
                code="idempotency_key_reused",
                message="The idempotency key was already used for another request",
                kind=FailureKind.CONFLICT,
            )
        if enqueued.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_CREATED,
                resources=(ResourceRef("job", str(enqueued.job.id)),),
            )
        return _operation_response(
            enqueued.job,
            kind="import",
            payload=enqueued.payload,
        )

    def enqueue_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        idempotency_key: str,
        automatic: bool = False,
    ) -> ZoteroOperation:
        credentials = self._require_credentials(actor, lock=True)
        operation_key = f"zotero-sync:{actor.id}:{idempotency_key}"
        existing = self._jobs.find_by_idempotency_key(key=operation_key)
        if existing is not None:
            payload = self._jobs.payload(
                requested_by_id=actor.id,
                job_id=existing.id,
            )
            if payload.get("automatic") is not automatic:
                raise AppError(
                    code="idempotency_key_reused",
                    message="The idempotency key was already used for another request",
                    kind=FailureKind.CONFLICT,
                )
            return _operation_response(existing, kind="sync", payload=payload)
        self._require_no_active_operation(actor=actor)
        targets = self._gateway.sync_targets(
            user_id=actor.id,
            limit=500,
            credential_revision=credentials.revision,
        )
        auto_import_cursor = (
            self._gateway.auto_import_cursor(user_id=actor.id) if automatic else None
        )
        job_id = uuid4()
        enqueued = self._jobs.enqueue(
            command=EnqueueJobCommand(
                job_id=job_id,
                operation=JobOperation.ZOTERO_SYNC,
                requested_by_id=actor.id,
                correlation_id=operation.trace.correlation_id,
                origin_operation_id=operation.trace.operation_id,
                idempotency_key=operation_key,
                payload={
                    "targets": [
                        {
                            "item_key": target.item_key,
                            "attachment_key": target.attachment_key,
                        }
                        for target in targets
                    ],
                    "automatic": automatic,
                    "auto_import_version": (
                        auto_import_cursor.library_version
                        if auto_import_cursor is not None
                        else None
                    ),
                    "auto_import_start": (
                        auto_import_cursor.start
                        if auto_import_cursor is not None
                        else 0
                    ),
                    "credential_revision": str(credentials.revision),
                },
                task_name="sync_zotero",
                queue=JobQueue.MAINTENANCE,
            )
        )
        if enqueued.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_CREATED,
                resources=(ResourceRef("job", str(enqueued.job.id)),),
            )
        return _operation_response(
            enqueued.job,
            kind="sync",
            payload=enqueued.payload,
        )

    def operation(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
        kind: Literal["import", "sync"],
    ) -> ZoteroOperation:
        job = self._jobs.get(requested_by_id=actor.id, job_id=operation_id)
        expected = (
            JobOperation.ZOTERO_IMPORT if kind == "import" else JobOperation.ZOTERO_SYNC
        )
        if job.operation != expected.value:
            raise AppError(
                code="zotero_operation_not_found",
                message="Zotero operation not found",
                kind=FailureKind.NOT_FOUND,
            )
        return _operation_response(
            job,
            kind=kind,
            payload=self._jobs.payload(
                requested_by_id=actor.id,
                job_id=operation_id,
            ),
        )

    def cancel_operation(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
        kind: Literal["import", "sync"],
    ) -> ZoteroOperation:
        self.operation(actor=actor, operation_id=operation_id, kind=kind)
        job = self._jobs.cancel(requested_by_id=actor.id, job_id=operation_id)
        return _operation_response(
            job,
            kind=kind,
            payload=self._jobs.payload(
                requested_by_id=actor.id,
                job_id=operation_id,
            ),
        )

    def complete_background_operation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        operation_id: UUID,
        claim_id: UUID,
        result: dict[str, JsonValue],
    ) -> bool:
        transition = self._idempotency.complete(
            operation_id=operation_id,
            claim_id=claim_id,
            result=result,
        )
        if not transition.changed:
            return False
        self._journal.append(
            actor=actor,
            operation=operation,
            action=JOB_COMPLETED,
            resources=(ResourceRef("job", str(operation_id)),),
        )
        return True

    def fail_background_operation(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        operation_id: UUID,
        claim_id: UUID,
        error_code: str,
    ) -> bool:
        transition = self._idempotency.fail(
            operation_id=operation_id,
            claim_id=claim_id,
            error_code=error_code,
        )
        if not transition.changed:
            return False
        self._journal.append(
            actor=actor,
            operation=operation,
            action=JOB_FAILED,
            resources=(ResourceRef("job", str(operation_id)),),
        )
        return True

    def claim_background_operation(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
    ) -> OperationClaim:
        return self._idempotency.claim_completion(
            operation_id=operation_id,
            requested_by_id=actor.id,
        )

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
        credential_revision: UUID,
    ) -> ZoteroImportPlan:
        return self._gateway.plan_import(
            actor=actor,
            items=items,
            credential_revision=credential_revision,
        )

    def reserve_import_item(
        self,
        *,
        actor: Actor,
        item_key: str,
        upload_job_id: UUID,
        credential_revision: UUID,
    ) -> UUID:
        return self._gateway.reserve_import_item(
            user_id=actor.id,
            item_key=item_key,
            upload_job_id=upload_job_id,
            credential_revision=credential_revision,
        )

    def fail_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
        credential_revision: UUID,
    ) -> None:
        change = self._gateway.fail_import_item(
            user_id=actor.id,
            item_key=item_key,
            upload_job_id=upload_job_id,
            error_code=error_code,
            credential_revision=credential_revision,
        )
        if change.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_IMPORT_FAILED,
                resources=(ResourceRef("zotero_import", str(change.imported_item_id)),),
            )

    def complete_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        upload_job_id: UUID,
        document_id: UUID,
        reused_document: bool,
        page_dimensions: PageDimensions,
        credential_revision: UUID,
    ) -> ZoteroImportItemResult:
        change = self._gateway.complete_import_item(
            actor=actor,
            item=item,
            attachment=attachment,
            upload_job_id=upload_job_id,
            document_id=document_id,
            reused_document=reused_document,
            page_dimensions=page_dimensions,
            credential_revision=credential_revision,
        )
        self._record_import_change(
            actor=actor,
            operation=operation,
            change=change,
            document_id=document_id,
            upload_job_id=upload_job_id,
        )
        return change.result

    def link_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
        credential_revision: UUID,
    ) -> ZoteroImportItemResult:
        change = self._gateway.link_import_item(
            actor=actor,
            item=item,
            attachment=attachment,
            document_id=document_id,
            page_dimensions=page_dimensions,
            credential_revision=credential_revision,
        )
        self._record_import_change(
            actor=actor,
            operation=operation,
            change=change,
            document_id=document_id,
            upload_job_id=None,
        )
        return change.result

    def complete_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch: ZoteroSyncBatch,
        credential_revision: UUID,
    ) -> ZoteroSyncResponse:
        mutation = self._gateway.apply_sync(
            actor=actor,
            batch=batch,
            credential_revision=credential_revision,
        )
        if mutation.changed_document_ids:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_ANNOTATIONS_SYNCED,
                resources=tuple(
                    ResourceRef("document", str(document_id))
                    for document_id in mutation.changed_document_ids
                ),
            )
        return mutation.response

    def sync_targets(
        self,
        *,
        actor: Actor,
        credential_revision: UUID,
    ) -> tuple[ZoteroSyncTarget, ...]:
        return self._gateway.sync_targets(
            user_id=actor.id,
            limit=500,
            credential_revision=credential_revision,
        )

    def auto_import_cursor(self, *, actor: Actor) -> ZoteroAutoImportCursor | None:
        return self._gateway.auto_import_cursor(user_id=actor.id)

    def advance_sync_checkpoint(
        self,
        *,
        actor: Actor,
        credential_revision: UUID,
        library_version: int | None,
        auto_import_cursor: ZoteroAutoImportCursor | None,
    ) -> bool:
        return self._gateway.advance_sync_checkpoint(
            user_id=actor.id,
            credential_revision=credential_revision,
            library_version=library_version,
            auto_import_cursor=auto_import_cursor,
        )

    def _record_import_change(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        change: ZoteroImportMutation,
        document_id: UUID,
        upload_job_id: UUID | None,
    ) -> None:
        if not change.changed:
            return
        resources = [
            ResourceRef("document", str(document_id)),
            ResourceRef("zotero_import", str(change.imported_item_id)),
        ]
        if upload_job_id is not None:
            resources.append(ResourceRef("job", str(upload_job_id)))
        self._journal.append(
            actor=actor,
            operation=operation,
            action=(
                ZOTERO_IMPORT_COMPLETED if change.completed else ZOTERO_IMPORT_STARTED
            ),
            resources=tuple(resources),
        )

    def _require_no_active_operation(self, *, actor: Actor) -> None:
        active = next(
            (
                job
                for job in self._jobs.list(
                    requested_by_id=actor.id,
                    project_id=None,
                    document_id=None,
                    operation=None,
                    statuses=(JobStatus.PENDING, JobStatus.RUNNING),
                )
                if job.operation
                in {JobOperation.ZOTERO_IMPORT.value, JobOperation.ZOTERO_SYNC.value}
            ),
            None,
        )
        if active is None:
            return
        raise AppError(
            code="zotero_operation_active",
            message="Another Zotero operation is already active",
            kind=FailureKind.CONFLICT,
            details={
                "operation_id": str(active.id),
                "operation_kind": (
                    "import"
                    if active.operation == JobOperation.ZOTERO_IMPORT.value
                    else "sync"
                ),
            },
        )

    def _require_credentials(
        self,
        actor: Actor,
        *,
        lock: bool = False,
    ) -> ZoteroCredentials:
        credentials = self._gateway.credentials(user_id=actor.id, lock=lock)
        require_zotero_connected(connected=credentials is not None)
        assert credentials is not None
        return credentials


def _operation_response(
    job: JobResponse,
    *,
    kind: Literal["import", "sync"],
    payload: dict[str, JsonValue],
) -> ZoteroOperation:
    result = job.result or {}
    raw_items = result.get("items")
    items: list[ZoteroOperationItem] = []
    if isinstance(raw_items, list):
        for value in raw_items:
            if isinstance(value, dict):
                try:
                    items.append(ZoteroOperationItem.model_validate(value))
                except ValueError:
                    continue
    if not items and job.status in {
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value,
    }:
        raw_item_keys = payload.get("item_keys")
        if not isinstance(raw_item_keys, list):
            raw_targets = payload.get("targets")
            raw_item_keys = (
                [
                    value.get("item_key")
                    for value in raw_targets
                    if isinstance(value, dict)
                ]
                if isinstance(raw_targets, list)
                else []
            )
        item_status: Literal["queued", "running"] = (
            "running" if job.status == JobStatus.RUNNING.value else "queued"
        )
        items = [
            ZoteroOperationItem(zotero_item_key=value, status=item_status)
            for value in raw_item_keys
            if isinstance(value, str) and value
        ]
    raw_counts = result.get("counts")
    try:
        counts = ZoteroOperationCounts.model_validate(raw_counts or {})
    except ValueError:
        total = len(items)
        counts = ZoteroOperationCounts(
            total=total,
            succeeded=sum(item.status == "accepted" for item in items),
            failed=sum(item.status == "failed" for item in items),
            skipped=sum(item.status == "cancelled" for item in items),
        )
    status: Literal[
        "queued",
        "running",
        "partial",
        "succeeded",
        "failed",
        "cancelled",
    ]
    if job.status == JobStatus.PENDING.value:
        status = "queued"
    elif job.status == JobStatus.RUNNING.value:
        status = "running"
    elif job.status == JobStatus.CANCELLED.value:
        status = "cancelled"
    elif job.status == JobStatus.FAILED.value:
        status = "failed"
    elif counts.failed and counts.succeeded:
        status = "partial"
    elif counts.failed and not counts.succeeded:
        status = "failed"
    else:
        status = "succeeded"
    return ZoteroOperation(
        id=job.id,
        kind=kind,
        status=status,
        progress_code=(
            cast(ZoteroOperationProgress, job.progress_code)
            if job.progress_code
            in {
                "queued",
                "fetching_library",
                "syncing_annotations",
                "importing_papers",
            }
            else "queued"
            if status == "queued"
            else None
        ),
        counts=counts,
        items=items,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
