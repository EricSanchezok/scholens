"""Short-transaction orchestration for Zotero provider workflows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import requests
from pydantic import ValidationError

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.zotero.application.contracts import (
    ZoteroCollection,
    ZoteroCollectionPage,
    ZoteroConnectResponse,
    ZoteroConnectionStatus,
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportResponse,
    ZoteroLibraryPage,
    ZoteroOAuthAuthorizationRequest,
    ZoteroSyncPreferencesRequest,
)
from app.modules.integrations.zotero.application.zotero import (
    PageDimensions,
    PreparedZoteroCallback,
    ZoteroAccessToken,
    ZoteroAttachmentSnapshot,
    ZoteroAutoImportCursor,
    ZoteroCredentials,
    ZoteroCollectionSnapshotPage,
    ZoteroImportPlan,
    ZoteroImportPlanItem,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncFailure,
    ZoteroSyncUpdate,
)
from app.modules.jobs.application.contracts import (
    ZoteroImportWebhookData,
    ZoteroSyncWebhookData,
    ZoteroWorkerImportItem,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.papers.application.ingestion import (
    AcceptedIngestion,
    IngestPaper,
    PreparedPaperInput,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SignedCursorCodec,
)
from app.shared.domain import AppError, FailureKind, JsonValue
from scholens_job_contracts import (
    ZOTERO_CALLBACK_HEARTBEAT_SECONDS,
    ZOTERO_CALLBACK_PROCESSING_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

_PERMANENT_AUTO_IMPORT_ERRORS = frozenset(
    {
        "zotero_item_not_found",
        "zotero_item_not_supported",
        "zotero_pdf_unavailable",
        "zotero_pdf_unsafe_address",
        "zotero_pdf_too_large",
        "zotero_pdf_encrypted",
    }
)


@dataclass(frozen=True, slots=True)
class _StagedZoteroImport:
    item: ZoteroItemSnapshot
    attachment: ZoteroAttachmentSnapshot
    object_key: str
    page_dimensions: PageDimensions


def _json_count(value: JsonValue | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _provider_error(exc: Exception) -> AppError:
    response = exc.response if isinstance(exc, requests.HTTPError) else None
    status = response.status_code if response is not None else None
    if status in {401, 403}:
        return AppError(
            code="zotero_permissions_insufficient",
            message="The Zotero connection no longer has the required permissions",
            kind=FailureKind.PERMISSION_DENIED,
            retryable=True,
        )
    if status == 429:
        return AppError(
            code="zotero_rate_limited",
            message="Zotero is temporarily rate limiting requests",
            kind=FailureKind.DEPENDENCY_FAILURE,
            retryable=True,
        )
    return AppError(
        code="zotero_unavailable",
        message="Zotero is temporarily unavailable",
        kind=FailureKind.DEPENDENCY_FAILURE,
        retryable=True,
    )


@dataclass(frozen=True, slots=True)
class ZoteroOAuthCallbackResult:
    return_path: str
    intent: str
    state: str


class ZoteroOperations(Protocol):
    def request_token(self) -> ZoteroRequestToken | None: ...

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str: ...

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None: ...

    def verify_access_token(self, *, access_token: ZoteroAccessToken) -> bool: ...

    def fetch_library(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int = 25,
        start: int = 0,
        query: str | None = None,
        collection_key: str | None = None,
        item_type: str | None = None,
        sort: str = "dateModified",
        direction: str = "desc",
    ) -> ZoteroLibrarySnapshot: ...

    def fetch_collections(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int,
        start: int,
    ) -> ZoteroCollectionSnapshotPage: ...

    def current_library_version(
        self, *, credentials: ZoteroCredentials
    ) -> int | None: ...

    async def fetch_page_dimensions(
        self,
        *,
        source_key: str | None,
    ) -> PageDimensions: ...

    async def upload_pdf(self, *, content: bytes) -> None: ...

    async def download_job_pdf(self, *, object_key: str) -> bytes: ...

    async def delete_job_pdf(self, *, object_key: str) -> None: ...


class ZoteroWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operations: ZoteroOperations,
        operation_factory: OperationContextFactory,
        cursors: SignedCursorCodec,
    ) -> None:
        self._executor = executor
        self._operations = operations
        self._operation_factory = operation_factory
        self._cursors = cursors

    def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ZoteroOAuthAuthorizationRequest,
    ) -> ZoteroConnectResponse:
        request_token = self._operations.request_token()
        if request_token is None:
            raise AppError(
                code="zotero_connection_failed",
                message="Zotero authorization is temporarily unavailable",
                kind=FailureKind.DEPENDENCY_FAILURE,
            )
        auth_url = self._operations.authorize_url(request_token=request_token)
        return self._executor.command(
            lambda capabilities: capabilities.zotero.save_oauth_request(
                actor=actor,
                operation=operation,
                request_token=request_token,
                auth_url=auth_url,
                return_path=request.return_path,
                intent=request.intent,
            )
        )

    def callback(
        self,
        *,
        oauth_token: str,
        oauth_verifier: str,
        request: RequestReference,
    ) -> ZoteroOAuthCallbackResult:
        callback = self._executor.command(
            lambda capabilities: capabilities.zotero.consume_oauth_callback(
                oauth_token=oauth_token,
                now=datetime.now(UTC),
            )
        )
        if callback is None:
            return ZoteroOAuthCallbackResult(
                return_path="/library",
                intent="manage",
                state="zotero_oauth_expired",
            )
        if callback.expires_at < datetime.now(UTC):
            return ZoteroOAuthCallbackResult(
                return_path=callback.return_path,
                intent=callback.intent,
                state="zotero_oauth_expired",
            )
        access_token = self._operations.exchange_access_token(
            callback=callback,
            verifier=oauth_verifier,
        )
        if access_token is None:
            return ZoteroOAuthCallbackResult(
                return_path=callback.return_path,
                intent=callback.intent,
                state="zotero_oauth_exchange_failed",
            )
        try:
            verified = self._operations.verify_access_token(access_token=access_token)
        except Exception as exc:
            logger.warning("zotero.oauth.permission_verification_failed")
            return ZoteroOAuthCallbackResult(
                return_path=callback.return_path,
                intent=callback.intent,
                state=_provider_error(exc).code,
            )
        if not verified:
            return ZoteroOAuthCallbackResult(
                return_path=callback.return_path,
                intent=callback.intent,
                state="zotero_permissions_insufficient",
            )
        actor = self._executor.query(
            lambda capabilities: capabilities.identity.resolve_actor_by_user_id(
                callback.user_id
            )
        )
        operation = self._operation_factory.resume(
            correlation_id=callback.correlation_id,
            causation_id=callback.origin_operation_id,
            initiated_by=OperationInitiator.SYSTEM,
            origin=OAuthCallbackOrigin(request=request, provider="zotero"),
            credential=None,
        )
        connected = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_oauth_callback(
                actor=actor,
                operation=operation,
                callback=callback,
                access_token=access_token,
            )
        )
        return ZoteroOAuthCallbackResult(
            return_path=callback.return_path,
            intent=callback.intent,
            state="connected" if connected else "zotero_connection_failed",
        )

    def status(self, *, actor: Actor) -> ZoteroConnectionStatus:
        return self._executor.query(
            lambda capabilities: capabilities.zotero.status(actor=actor)
        )

    def set_sync_preferences(
        self,
        *,
        actor: Actor,
        request: ZoteroSyncPreferencesRequest,
    ) -> ZoteroConnectionStatus:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_library(actor=actor)
        )
        try:
            version = (
                self._operations.current_library_version(credentials=credentials)
                if request.auto_import_enabled
                else None
            )
        except Exception as exc:
            raise _provider_error(exc) from exc
        return self._executor.command(
            lambda capabilities: capabilities.zotero.set_sync_preferences(
                actor=actor,
                request=request,
                library_version=version,
            )
        )

    def library(
        self,
        *,
        actor: Actor,
        cursor: str | None,
        query: str | None,
        collection_key: str | None,
        item_type: str | None,
        sort: str,
        limit: int,
    ) -> ZoteroLibraryPage:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_library(actor=actor)
        )
        fingerprint = ":".join(
            (
                str(actor.id),
                "items",
                (query or "").casefold(),
                collection_key or "",
                item_type or "",
                sort,
                str(limit),
            )
        )
        start = (
            self._cursors.decode(cursor=cursor, fingerprint=fingerprint)
            if cursor
            else 0
        )
        provider_sort, direction = _zotero_sort(sort)
        try:
            snapshot = self._operations.fetch_library(
                credentials=credentials,
                limit=limit,
                start=start,
                query=query,
                collection_key=collection_key,
                item_type=item_type,
                sort=provider_sort,
                direction=direction,
            )
        except Exception as exc:
            raise _provider_error(exc) from exc
        response = self._executor.query(
            lambda capabilities: capabilities.zotero.library(
                actor=actor,
                snapshot=snapshot,
            )
        )
        return response.model_copy(
            update={
                "previous_cursor": (
                    self._cursors.encode(
                        fingerprint=fingerprint,
                        offset=max(0, start - limit),
                    )
                    if start > 0
                    else None
                ),
                "next_cursor": (
                    self._cursors.encode(
                        fingerprint=fingerprint,
                        offset=start + limit,
                    )
                    if start + len(response.items) < response.total_count
                    else None
                ),
            }
        )

    def collections(
        self,
        *,
        actor: Actor,
        cursor: str | None,
        limit: int,
    ) -> ZoteroCollectionPage:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_library(actor=actor)
        )
        fingerprint = f"{actor.id}:collections:{limit}"
        start = (
            self._cursors.decode(cursor=cursor, fingerprint=fingerprint)
            if cursor
            else 0
        )
        try:
            page = self._operations.fetch_collections(
                credentials=credentials,
                limit=limit,
                start=start,
            )
        except Exception as exc:
            raise _provider_error(exc) from exc
        return ZoteroCollectionPage(
            items=[
                ZoteroCollection(key=item.key, name=item.name) for item in page.items
            ],
            previous_cursor=(
                self._cursors.encode(
                    fingerprint=fingerprint,
                    offset=max(0, start - limit),
                )
                if start > 0
                else None
            ),
            next_cursor=(
                self._cursors.encode(
                    fingerprint=fingerprint,
                    offset=start + limit,
                )
                if start + len(page.items) < page.total_count
                else None
            ),
            total_count=page.total_count,
        )


class ZoteroBackgroundWorkflow:
    """Apply provider work returned by Jobs without exposing credentials in payloads."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operations: ZoteroOperations,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._operations = operations
        self._operation_factory = operation_factory

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        payload: dict[str, object],
    ) -> object:
        if actor is None:
            raise AppError(
                code="job_owner_missing",
                message="The Zotero job owner no longer exists",
                kind=FailureKind.NOT_FOUND,
            )
        kind = payload.get("operation")
        callback: ZoteroImportWebhookData | ZoteroSyncWebhookData | None
        invalid_callback = False
        try:
            callback = (
                ZoteroImportWebhookData.model_validate(payload)
                if kind == "import"
                else ZoteroSyncWebhookData.model_validate(payload)
                if kind == "sync"
                else None
            )
        except ValidationError:
            callback = None
            invalid_callback = True
        raw_task_id = payload.get("task_id")
        try:
            callback_task_id = UUID(str(raw_task_id)) if raw_task_id else None
        except ValueError:
            callback_task_id = None
        if callback_task_id is not None and callback_task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Zotero job callback does not match",
                kind=FailureKind.CONFLICT,
            )
        if callback is None and not invalid_callback:
            raise AppError(
                code="job_callback_mismatch",
                message="Zotero job callback does not match",
                kind=FailureKind.CONFLICT,
            )
        if callback is not None and callback.task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Zotero job callback does not match",
                kind=FailureKind.CONFLICT,
            )
        claim = self._executor.command(
            lambda capabilities: capabilities.zotero.claim_background_operation(
                actor=actor,
                operation_id=job_id,
            )
        )
        if not claim.acquired or claim.claim_id is None:
            return {"accepted": False}
        claim_id = claim.claim_id
        outcome_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        if invalid_callback:
            changed = self._executor.command(
                lambda capabilities: capabilities.zotero.fail_background_operation(
                    actor=actor,
                    operation=outcome_operation,
                    operation_id=job_id,
                    claim_id=claim_id,
                    error_code="zotero_callback_payload_invalid",
                )
            )
            return (
                {"accepted": True, "status": "failed"}
                if changed
                else {"accepted": False}
            )
        assert callback is not None
        heartbeat_stop = asyncio.Event()
        heartbeat_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_callback_claim(
                actor=actor,
                operation_id=job_id,
                claim_id=claim_id,
                stop=heartbeat_stop,
                lost=heartbeat_lost,
            )
        )
        try:
            try:
                async with asyncio.timeout(ZOTERO_CALLBACK_PROCESSING_TIMEOUT_SECONDS):
                    return await self._complete_claimed(
                        actor=actor,
                        operation=outcome_operation,
                        job_id=job_id,
                        claim_id=claim_id,
                        callback=callback,
                        heartbeat_lost=heartbeat_lost,
                    )
            except TimeoutError:
                changed = self._executor.command(
                    lambda capabilities: capabilities.zotero.fail_background_operation(
                        actor=actor,
                        operation=outcome_operation,
                        operation_id=job_id,
                        claim_id=claim_id,
                        error_code="zotero_callback_processing_timeout",
                    )
                )
                return (
                    {"accepted": True, "status": "failed"}
                    if changed
                    else {"accepted": False}
                )
        finally:
            heartbeat_stop.set()
            await heartbeat_task

    async def _complete_claimed(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        claim_id: UUID,
        callback: ZoteroImportWebhookData | ZoteroSyncWebhookData,
        heartbeat_lost: asyncio.Event,
    ) -> object:
        def maintain_claim() -> None:
            if heartbeat_lost.is_set() or not self._executor.command(
                lambda capabilities: capabilities.zotero.heartbeat_background_operation(
                    actor=actor,
                    operation_id=job_id,
                    claim_id=claim_id,
                )
            ):
                raise AppError(
                    code="zotero_callback_lease_lost",
                    message="The Zotero callback claim is no longer current",
                    kind=FailureKind.CONFLICT,
                )

        revision_is_current = self._executor.query(
            lambda capabilities: capabilities.zotero.credential_revision_is_current(
                user_id=actor.id,
                revision=callback.credential_revision,
            )
        )
        if not revision_is_current:
            self._executor.command(
                lambda capabilities: capabilities.zotero.fail_background_operation(
                    actor=actor,
                    operation=operation,
                    operation_id=job_id,
                    claim_id=claim_id,
                    error_code="zotero_credentials_rotated",
                )
            )
            return {"accepted": True, "status": "failed"}
        self._executor.command(
            lambda capabilities: capabilities.integrations.record_outcome(
                actor=actor,
                operation=operation,
                provider=IntegrationProvider.ZOTERO,
                credential_revision=callback.credential_revision,
                outcome=callback.credential_outcome,
                error_code=callback.error_code,
            )
        )
        if callback.error_code:
            self._executor.command(
                lambda capabilities: capabilities.zotero.fail_background_operation(
                    actor=actor,
                    operation=operation,
                    operation_id=job_id,
                    claim_id=claim_id,
                    error_code=callback.error_code or "zotero_unavailable",
                )
            )
            return {"accepted": True, "status": "failed"}
        try:
            if isinstance(callback, ZoteroImportWebhookData):
                result = await self._apply_import_items(
                    actor=actor,
                    operation=operation,
                    items=callback.items,
                    credential_revision=callback.credential_revision,
                    maintain_claim=maintain_claim,
                )
            else:
                result = await self._apply_sync(
                    actor=actor,
                    operation=operation,
                    callback=callback,
                    maintain_claim=maintain_claim,
                )
        except AppError as exc:
            if exc.code == "zotero_callback_lease_lost":
                return {"accepted": False}
            if exc.code != "zotero_credentials_rotated":
                raise
            self._executor.command(
                lambda capabilities: capabilities.zotero.fail_background_operation(
                    actor=actor,
                    operation=operation,
                    operation_id=job_id,
                    claim_id=claim_id,
                    error_code="zotero_credentials_rotated",
                )
            )
            return {"accepted": True, "status": "failed"}
        maintain_claim()
        completed = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_background_operation(
                actor=actor,
                operation=operation,
                operation_id=job_id,
                claim_id=claim_id,
                result=result,
            )
        )
        return {"accepted": completed}

    async def _heartbeat_callback_claim(
        self,
        *,
        actor: Actor,
        operation_id: UUID,
        claim_id: UUID,
        stop: asyncio.Event,
        lost: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=ZOTERO_CALLBACK_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                try:
                    maintained = self._executor.command(
                        lambda capabilities: (
                            capabilities.zotero.heartbeat_background_operation(
                                actor=actor,
                                operation_id=operation_id,
                                claim_id=claim_id,
                            )
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "zotero.callback_heartbeat.failed",
                        extra={"exception_type": type(exc).__name__},
                    )
                    continue
                if not maintained:
                    lost.set()
                    return

    async def _apply_import_items(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        items: list[ZoteroWorkerImportItem],
        credential_revision: UUID,
        maintain_claim: Callable[[], None],
    ) -> dict[str, JsonValue]:
        ready = [item for item in items if item.status == "ready"]
        staged: dict[str, _StagedZoteroImport] = {}
        cleanup: list[str] = []
        cleanup_owned = True
        worker_errors = [
            ZoteroImportError(
                zotero_item_key=item.item_key,
                error=item.error_code or "zotero_import_failed",
            )
            for item in items
            if item.status == "failed"
        ]
        try:
            for item in ready:
                assert item.metadata is not None
                assert item.attachment is not None
                assert item.s3_object_key is not None
                cleanup.append(item.s3_object_key)
                snapshot = ZoteroItemSnapshot(**item.metadata.model_dump(mode="python"))
                attachment = ZoteroAttachmentSnapshot(
                    item_key=item.attachment.item_key,
                    import_source=item.attachment.import_source,
                    attachment_key=item.attachment.attachment_key,
                    source_url=item.attachment.source_url,
                    annotations_json=item.attachment.annotations_json,
                    version=item.attachment.version,
                )
                staged[item.item_key] = _StagedZoteroImport(
                    item=snapshot,
                    attachment=attachment,
                    object_key=item.s3_object_key,
                    page_dimensions=tuple(item.page_dimensions),
                )
            maintain_claim()
            plan = self._executor.command(
                lambda capabilities: capabilities.zotero.plan_import(
                    actor=actor,
                    items=tuple(value.item for value in staged.values()),
                    credential_revision=credential_revision,
                )
            )
            applied = await _execute_import_plan(
                executor=self._executor,
                operations=self._operations,
                operation_factory=self._operation_factory,
                actor=actor,
                operation=operation,
                plan=plan,
                staged_by_item_key=staged,
                credential_revision=credential_revision,
                maintain_claim=maintain_claim,
            )
        except asyncio.CancelledError:
            cleanup_owned = False
            raise
        except AppError as exc:
            if exc.code == "zotero_callback_lease_lost":
                cleanup_owned = False
            raise
        finally:
            if cleanup_owned:
                for object_key in cleanup:
                    try:
                        await self._operations.delete_job_pdf(object_key=object_key)
                    except Exception:
                        logger.warning(
                            "zotero.job_object.cleanup_failed",
                            extra={"object_prefix": "zotero-imports"},
                            exc_info=True,
                        )
        errors = [*worker_errors, *applied.errors]
        results: list[JsonValue] = []
        for imported in applied.imported:
            results.append(
                {
                    "zotero_item_key": imported.zotero_item_key,
                    "status": "accepted",
                    "title": imported.title,
                    "document_id": str(imported.document_id),
                    "ingestion_job_id": (
                        str(imported.upload_job_id) if imported.upload_job_id else None
                    ),
                }
            )
        for error in errors:
            results.append(
                {
                    "zotero_item_key": error.zotero_item_key,
                    "status": "failed",
                    "error_code": error.error,
                }
            )
        for item_key in applied.skipped_item_keys:
            results.append(
                {
                    "zotero_item_key": item_key,
                    "status": "cancelled",
                }
            )
        return {
            "counts": {
                "total": len(items),
                "succeeded": applied.imported_count,
                "failed": len(errors),
                "skipped": applied.skipped_already_imported,
            },
            "items": results,
        }

    async def _apply_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        callback: ZoteroSyncWebhookData,
        maintain_claim: Callable[[], None],
    ) -> dict[str, JsonValue]:
        maintain_claim()
        sync_targets = self._executor.command(
            lambda capabilities: capabilities.zotero.sync_targets(
                actor=actor,
                credential_revision=callback.credential_revision,
            )
        )
        targets = {target.item_key: target for target in sync_targets}
        updates = []
        for value in callback.updates:
            maintain_claim()
            target = targets.get(value.item_key)
            if target is None or target.attachment_key != value.attachment_key:
                continue
            dimensions = await self._operations.fetch_page_dimensions(
                source_key=target.document_source_key
            )
            updates.append(
                ZoteroSyncUpdate(
                    target=target,
                    annotations_json=value.annotations_json,
                    page_dimensions=dimensions,
                )
            )
        maintain_claim()
        sync_result = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_sync(
                actor=actor,
                operation=operation,
                batch=ZoteroSyncBatch(
                    updates=tuple(updates),
                    failures=tuple(
                        ZoteroSyncFailure(
                            item_key=failure.item_key,
                            error_code=failure.error_code,
                        )
                        for failure in callback.failures
                    ),
                ),
                credential_revision=callback.credential_revision,
            )
        )
        import_result = await self._apply_import_items(
            actor=actor,
            operation=operation,
            items=callback.auto_imports,
            credential_revision=callback.credential_revision,
            maintain_claim=maintain_claim,
        )
        library_version = callback.library_version
        auto_import_cursor = _recoverable_auto_import_cursor(
            callback=callback,
            import_result=import_result,
        )
        maintain_claim()
        checkpoint_advanced = self._executor.command(
            lambda capabilities: capabilities.zotero.advance_sync_checkpoint(
                actor=actor,
                credential_revision=callback.credential_revision,
                library_version=library_version,
                auto_import_cursor=auto_import_cursor,
            )
        )
        if not checkpoint_advanced:
            raise AppError(
                code="zotero_credentials_rotated",
                message="The Zotero connection changed before sync completed",
                kind=FailureKind.CONFLICT,
            )
        import_counts = import_result.get("counts")
        assert isinstance(import_counts, dict)
        imported = _json_count(import_counts.get("succeeded"))
        import_failed = _json_count(import_counts.get("failed"))
        skipped = _json_count(import_counts.get("skipped"))
        return {
            "counts": {
                "total": len(callback.updates)
                + len(callback.failures)
                + len(callback.auto_imports),
                "succeeded": sync_result.synced_papers_count + imported,
                "failed": len(callback.failures) + import_failed,
                "skipped": skipped,
            },
            "items": import_result.get("items") or [],
            "synced_papers_count": sync_result.synced_papers_count,
            "new_annotations_count": sync_result.new_annotations_count,
            "auto_imported_count": imported,
        }


def _recoverable_auto_import_cursor(
    *,
    callback: ZoteroSyncWebhookData,
    import_result: dict[str, JsonValue],
) -> ZoteroAutoImportCursor | None:
    raw_results = import_result.get("items")
    results_by_key = (
        {
            str(value.get("zotero_item_key")): value
            for value in raw_results
            if isinstance(raw_results, list)
            and isinstance(value, dict)
            and value.get("zotero_item_key")
        }
        if isinstance(raw_results, list)
        else {}
    )
    cursor: ZoteroAutoImportCursor | None = None
    all_resolved = True
    resolved_count = 0
    for item in callback.auto_imports:
        result = results_by_key.get(item.item_key)
        status = result.get("status") if result is not None else None
        error_code = result.get("error_code") if result is not None else None
        resolved = status in {"accepted", "cancelled"} or (
            status == "failed" and error_code in _PERMANENT_AUTO_IMPORT_ERRORS
        )
        if not resolved:
            all_resolved = False
            break
        resolved_count += 1
    if all_resolved and callback.auto_import_caught_up_version is not None:
        return ZoteroAutoImportCursor(
            library_version=callback.auto_import_caught_up_version,
            start=0,
        )
    if callback.auto_import_base_version is not None and resolved_count:
        cursor = ZoteroAutoImportCursor(
            library_version=callback.auto_import_base_version,
            start=callback.auto_import_base_start + resolved_count,
        )
    return cursor


def _zotero_sort(value: str) -> tuple[str, str]:
    return {
        "modified_desc": ("dateModified", "desc"),
        "added_desc": ("dateAdded", "desc"),
        "published_desc": ("date", "desc"),
        "title_asc": ("title", "asc"),
        "creator_asc": ("creator", "asc"),
    }.get(value, ("dateModified", "desc"))


async def _execute_planned_import(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operations: ZoteroOperations,
    operation_factory: OperationContextFactory,
    actor: Actor,
    operation: OperationContext,
    planned: ZoteroImportPlanItem,
    staged: _StagedZoteroImport,
    credential_revision: UUID,
    maintain_claim: Callable[[], None],
) -> tuple[ZoteroImportItemResult | None, UUID | None, ZoteroImportError | None]:
    """Consume one staged PDF so callback memory never scales with batch size."""
    accept_operation = operation_factory.child(
        operation,
        initiated_by=OperationInitiator.SYSTEM,
    )
    proposed_job_id = uuid4()
    ingestion: IngestPaper | None = None
    acquired = False
    try:
        maintain_claim()
        pdf_content = await operations.download_job_pdf(object_key=staged.object_key)
        maintain_claim()
        prepared_paper = PreparedPaperInput(
            content=pdf_content,
            filename=f"zotero-{planned.item.item_key}.pdf",
            display_name=planned.item.title or f"Zotero {planned.item.item_key}",
            source_kind="upload",
        )
        ingestion = executor.query(lambda capabilities: capabilities.paper_ingestion)
        await ingestion.acquire(actor=actor, job_id=proposed_job_id)
        acquired = True
        maintain_claim()
        await operations.upload_pdf(content=pdf_content)
        maintain_claim()

        def accept(
            capabilities: ApplicationCapabilities,
        ) -> tuple[AcceptedIngestion, ZoteroImportItemResult]:
            accepted = capabilities.paper_ingestion.accept(
                actor=actor,
                operation=accept_operation,
                prepared=prepared_paper,
                project_id=None,
                add_to_library=True,
                idempotency_key=(
                    f"zotero:{planned.item.item_key}:"
                    f"{accept_operation.trace.operation_id}"
                ),
                job_id=proposed_job_id,
            )
            document_id = accepted.ingestion.document_id
            if document_id is None:
                raise RuntimeError("accepted_zotero_ingestion_has_no_document")
            capabilities.zotero.reserve_import_item(
                actor=actor,
                item_key=planned.item.item_key,
                upload_job_id=accepted.ingestion.id,
                credential_revision=credential_revision,
            )
            item_result = capabilities.zotero.complete_import_item(
                actor=actor,
                operation=accept_operation,
                item=planned.item,
                attachment=staged.attachment,
                upload_job_id=accepted.ingestion.id,
                document_id=document_id,
                reused_document=not accepted.processing_required,
                page_dimensions=staged.page_dimensions,
                credential_revision=credential_revision,
            )
            return accepted, item_result

        accepted, item_result = executor.command(accept)
        document_id = accepted.ingestion.document_id
        if document_id is None:
            raise RuntimeError("accepted_zotero_ingestion_has_no_document")
        if (
            accepted.replayed
            or accepted.ingestion.id != proposed_job_id
            or not accepted.processing_required
        ):
            await ingestion.release(actor=actor, job_id=proposed_job_id)
            acquired = False
        return item_result, document_id, None
    except asyncio.CancelledError:
        if acquired and ingestion is not None:
            await ingestion.release(actor=actor, job_id=proposed_job_id)
        raise
    except Exception as exc:
        if acquired and ingestion is not None:
            await ingestion.release(actor=actor, job_id=proposed_job_id)
        if isinstance(exc, AppError) and exc.code in {
            "zotero_credentials_rotated",
            "zotero_callback_lease_lost",
        }:
            raise
        logger.exception(
            "zotero.item_import.failed",
            extra={"zotero_item_key": planned.item.item_key},
        )
        maintain_claim()
        failure_operation = operation_factory.child(
            accept_operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        executor.command(
            lambda capabilities: capabilities.zotero.fail_import_item(
                actor=actor,
                operation=failure_operation,
                item_key=planned.item.item_key,
                upload_job_id=None,
                error_code="zotero_import_failed",
                credential_revision=credential_revision,
            )
        )
        return (
            None,
            None,
            ZoteroImportError(
                zotero_item_key=planned.item.item_key,
                error="zotero_import_failed",
            ),
        )


async def _execute_import_plan(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operations: ZoteroOperations,
    operation_factory: OperationContextFactory,
    actor: Actor,
    operation: OperationContext,
    plan: ZoteroImportPlan,
    staged_by_item_key: dict[str, _StagedZoteroImport],
    credential_revision: UUID,
    maintain_claim: Callable[[], None],
) -> ZoteroImportResponse:
    imported = []
    errors = list(plan.errors)
    document_by_item_key: dict[str, UUID] = {}
    dimensions_by_item_key: dict[str, PageDimensions] = {}

    for planned in plan.items:
        if planned.disposition == "link_existing":
            existing_document_id = planned.document_id
            assert existing_document_id is not None
            staged = staged_by_item_key.get(planned.item.item_key)
            if staged is None:
                raise RuntimeError("zotero_worker_import_content_missing")
            attachment = staged.attachment
            page_dimensions = staged.page_dimensions
            maintain_claim()
            link_operation = operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            executor.command(
                lambda capabilities: capabilities.zotero.link_import_item(
                    actor=actor,
                    operation=link_operation,
                    item=planned.item,
                    attachment=attachment,
                    document_id=existing_document_id,
                    page_dimensions=page_dimensions,
                    credential_revision=credential_revision,
                )
            )
            continue
        if planned.disposition == "link_batch":
            continue

        staged = staged_by_item_key.get(planned.item.item_key)
        if staged is None:
            raise RuntimeError("zotero_worker_import_content_missing")
        item_result, document_id, error = await _execute_planned_import(
            executor=executor,
            operations=operations,
            operation_factory=operation_factory,
            actor=actor,
            operation=operation,
            planned=planned,
            staged=staged,
            credential_revision=credential_revision,
            maintain_claim=maintain_claim,
        )
        if error is not None:
            errors.append(error)
            continue
        assert item_result is not None
        assert document_id is not None
        imported.append(item_result)
        document_by_item_key[planned.item.item_key] = document_id
        dimensions_by_item_key[planned.item.item_key] = staged.page_dimensions

    for planned in plan.items:
        if planned.disposition != "link_batch":
            continue
        source_item_key = planned.source_item_key
        assert source_item_key is not None
        document_id = document_by_item_key.get(source_item_key)
        if document_id is None:
            errors.append(
                ZoteroImportError(
                    zotero_item_key=planned.item.item_key,
                    error="zotero_import_failed",
                )
            )
            continue
        staged = staged_by_item_key.get(planned.item.item_key)
        if staged is None:
            raise RuntimeError("zotero_worker_import_content_missing")
        maintain_claim()
        link_operation = operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        executor.command(
            lambda capabilities: capabilities.zotero.link_import_item(
                actor=actor,
                operation=link_operation,
                item=planned.item,
                attachment=staged.attachment,
                document_id=document_id,
                page_dimensions=dimensions_by_item_key.get(
                    source_item_key,
                    (),
                ),
                credential_revision=credential_revision,
            )
        )

    return ZoteroImportResponse(
        imported=imported,
        imported_count=len(imported),
        imported_via_url=sum(item.import_source == "url" for item in imported),
        skipped_already_imported=plan.skipped_already_imported,
        skipped_item_keys=list(plan.skipped_item_keys),
        errors=errors,
    )


__all__ = ["ZoteroBackgroundWorkflow", "ZoteroOperations", "ZoteroWorkflow"]
