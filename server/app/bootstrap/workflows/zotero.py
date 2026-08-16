"""Short-transaction orchestration for Zotero provider workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import requests

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
    ZoteroCredentials,
    ZoteroCollectionSnapshotPage,
    ZoteroImportContent,
    ZoteroImportPlan,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroRequestToken,
    ZoteroSyncBatch,
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

logger = logging.getLogger(__name__)


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
        callback = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_oauth_callback(
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
        callback = (
            ZoteroImportWebhookData.model_validate(payload)
            if kind == "import"
            else ZoteroSyncWebhookData.model_validate(payload)
            if kind == "sync"
            else None
        )
        if callback is None or callback.task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Zotero job callback does not match",
                kind=FailureKind.CONFLICT,
            )
        outcome_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
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
                    operation=outcome_operation,
                    operation_id=job_id,
                    error_code="zotero_credentials_rotated",
                )
            )
            return {"accepted": True, "status": "failed"}
        self._executor.command(
            lambda capabilities: capabilities.integrations.record_outcome(
                actor=actor,
                operation=outcome_operation,
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
                    operation=outcome_operation,
                    operation_id=job_id,
                    error_code=callback.error_code or "zotero_unavailable",
                )
            )
            return {"accepted": True, "status": "failed"}
        if isinstance(callback, ZoteroImportWebhookData):
            result = await self._apply_import_items(
                actor=actor,
                operation=outcome_operation,
                items=callback.items,
            )
        else:
            result = await self._apply_sync(
                actor=actor,
                operation=outcome_operation,
                callback=callback,
            )
        completed = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_background_operation(
                actor=actor,
                operation=outcome_operation,
                operation_id=job_id,
                result=result,
            )
        )
        return {"accepted": completed}

    async def _apply_import_items(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        items: list[ZoteroWorkerImportItem],
    ) -> dict[str, JsonValue]:
        ready = [item for item in items if item.status == "ready"]
        contents: dict[str, ZoteroImportContent] = {}
        cleanup: list[str] = []
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
                content = await self._operations.download_job_pdf(
                    object_key=item.s3_object_key
                )
                snapshot = ZoteroItemSnapshot(**item.metadata.model_dump(mode="python"))
                attachment = ZoteroAttachmentSnapshot(
                    item_key=item.attachment.item_key,
                    import_source=item.attachment.import_source,
                    attachment_key=item.attachment.attachment_key,
                    source_url=item.attachment.source_url,
                    annotations_json=item.attachment.annotations_json,
                    version=item.attachment.version,
                )
                contents[item.item_key] = ZoteroImportContent(
                    item=snapshot,
                    attachment=attachment,
                    pdf_content=content,
                    page_dimensions=tuple(item.page_dimensions),
                    error=None,
                )
            plan = self._executor.query(
                lambda capabilities: capabilities.zotero.plan_import(
                    actor=actor,
                    items=tuple(content.item for content in contents.values()),
                )
            )
            applied = await _execute_import_plan(
                executor=self._executor,
                operations=self._operations,
                operation_factory=self._operation_factory,
                actor=actor,
                operation=operation,
                plan=plan,
                content_by_item_key=contents,
            )
        finally:
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
    ) -> dict[str, JsonValue]:
        sync_targets = self._executor.query(
            lambda capabilities: capabilities.zotero.sync_targets(actor=actor)
        )
        targets = {target.item_key: target for target in sync_targets}
        updates = []
        for value in callback.updates:
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
        sync_result = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_sync(
                actor=actor,
                operation=operation,
                batch=ZoteroSyncBatch(
                    updates=tuple(updates),
                    failed_item_keys=tuple(
                        failure.item_key for failure in callback.failures
                    ),
                ),
            )
        )
        import_result = await self._apply_import_items(
            actor=actor,
            operation=operation,
            items=callback.auto_imports,
        )
        library_version = callback.library_version
        self._executor.command(
            lambda capabilities: capabilities.zotero.advance_sync_checkpoint(
                actor=actor,
                credential_revision=callback.credential_revision,
                library_version=library_version,
            )
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


def _zotero_sort(value: str) -> tuple[str, str]:
    return {
        "modified_desc": ("dateModified", "desc"),
        "added_desc": ("dateAdded", "desc"),
        "published_desc": ("date", "desc"),
        "title_asc": ("title", "asc"),
        "creator_asc": ("creator", "asc"),
    }.get(value, ("dateModified", "desc"))


async def _execute_import_plan(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operations: ZoteroOperations,
    operation_factory: OperationContextFactory,
    actor: Actor,
    operation: OperationContext,
    plan: ZoteroImportPlan,
    content_by_item_key: dict[str, ZoteroImportContent],
) -> ZoteroImportResponse:
    imported = []
    errors = list(plan.errors)
    document_by_item_key: dict[str, UUID] = {}
    dimensions_by_item_key: dict[str, PageDimensions] = {}

    for planned in plan.items:
        if planned.disposition == "link_existing":
            existing_document_id = planned.document_id
            assert existing_document_id is not None
            prepared_content = content_by_item_key.get(planned.item.item_key)
            if prepared_content is None:
                raise RuntimeError("zotero_worker_import_content_missing")
            attachment = prepared_content.attachment
            page_dimensions = prepared_content.page_dimensions
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
                )
            )
            continue
        if planned.disposition == "link_batch":
            continue

        content = content_by_item_key.get(planned.item.item_key)
        if content is None:
            raise RuntimeError("zotero_worker_import_content_missing")
        if content.pdf_content is None:
            error_code = content.error or "No PDF available"
            failure_operation = operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            executor.command(
                lambda capabilities: capabilities.zotero.fail_import_item(
                    actor=actor,
                    operation=failure_operation,
                    item_key=planned.item.item_key,
                    upload_job_id=None,
                    error_code=error_code,
                )
            )
            errors.append(
                ZoteroImportError(
                    zotero_item_key=planned.item.item_key,
                    error=error_code,
                )
            )
            continue

        prepared_paper = PreparedPaperInput(
            content=content.pdf_content,
            filename=f"zotero-{planned.item.item_key}.pdf",
            display_name=planned.item.title or f"Zotero {planned.item.item_key}",
            source_kind="upload",
        )
        accept_operation = operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        proposed_job_id = uuid4()
        ingestion: IngestPaper | None = None
        acquired = False

        try:
            ingestion = executor.query(
                lambda capabilities: capabilities.paper_ingestion
            )
            await ingestion.acquire(actor=actor, job_id=proposed_job_id)
            acquired = True
            await operations.upload_pdf(content=content.pdf_content)

            def accept(
                capabilities: ApplicationCapabilities,
            ) -> tuple[AcceptedIngestion, ZoteroImportItemResult]:
                accepted = capabilities.paper_ingestion.accept(
                    actor=actor,
                    operation=accept_operation,
                    prepared=prepared_paper,
                    project_id=None,
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
                )
                item_result = capabilities.zotero.complete_import_item(
                    actor=actor,
                    operation=accept_operation,
                    item=planned.item,
                    attachment=content.attachment,
                    upload_job_id=accepted.ingestion.id,
                    document_id=document_id,
                    reused_document=not accepted.processing_required,
                    page_dimensions=content.page_dimensions,
                )
                return accepted, item_result

            accepted, item_result = executor.command(accept)
            imported.append(item_result)
            document_id = accepted.ingestion.document_id
            if document_id is None:
                raise RuntimeError("accepted_zotero_ingestion_has_no_document")
            document_by_item_key[planned.item.item_key] = document_id
            dimensions_by_item_key[planned.item.item_key] = content.page_dimensions
            if (
                accepted.replayed
                or accepted.ingestion.id != proposed_job_id
                or not accepted.processing_required
            ):
                await ingestion.release(actor=actor, job_id=proposed_job_id)
                acquired = False
        except Exception:
            logger.exception(
                "zotero.item_import.failed",
                extra={"zotero_item_key": planned.item.item_key},
            )
            if acquired and ingestion is not None:
                await ingestion.release(actor=actor, job_id=proposed_job_id)
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
                )
            )
            errors.append(
                ZoteroImportError(
                    zotero_item_key=planned.item.item_key,
                    error="zotero_import_failed",
                )
            )

    for planned in plan.items:
        if planned.disposition != "link_batch":
            continue
        source_item_key = planned.source_item_key
        assert source_item_key is not None
        document_id = document_by_item_key.get(source_item_key)
        if document_id is None:
            continue
        prepared_content = content_by_item_key.get(planned.item.item_key)
        if prepared_content is None:
            raise RuntimeError("zotero_worker_import_content_missing")
        link_operation = operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        executor.command(
            lambda capabilities: capabilities.zotero.link_import_item(
                actor=actor,
                operation=link_operation,
                item=planned.item,
                attachment=prepared_content.attachment,
                document_id=document_id,
                page_dimensions=dimensions_by_item_key.get(
                    source_item_key,
                    (),
                ),
            )
        )

    return ZoteroImportResponse(
        imported=imported,
        imported_count=len(imported),
        imported_via_url=sum(item.import_source == "url" for item in imported),
        skipped_already_imported=plan.skipped_already_imported,
        errors=errors,
    )


__all__ = ["ZoteroBackgroundWorkflow", "ZoteroOperations", "ZoteroWorkflow"]
