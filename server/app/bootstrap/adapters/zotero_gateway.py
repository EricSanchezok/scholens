"""SQLAlchemy gateway for Zotero connection and import state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from typing import Literal
from uuid import UUID

from app.bootstrap.adapters.zotero_annotations import apply_annotation_snapshot
from app.database.models import Document, ZoteroImportSource, ZoteroImportStatus
from app.modules.papers.domain import normalize_doi
from app.modules.billing.infrastructure.quotas import (
    can_user_auto_sync_zotero,
    can_user_upload_paper,
    get_remaining_paper_upload_slots,
)
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectionStatus,
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroLibraryItem,
    ZoteroLibraryPage,
    ZoteroSyncPreferencesRequest,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    ZoteroConnectionRepository,
)
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    PageDimensions,
    ZoteroAccessToken,
    ZoteroAttachmentSnapshot,
    ZoteroAutoImportCursor,
    ZoteroConnectionChange,
    ZoteroCredentials,
    ZoteroImportMutation,
    ZoteroImportPlan,
    ZoteroImportPlanItem,
    ZoteroItemMutation,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncMutation,
    ZoteroSyncTarget,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.tag_repository import library_tag_repository
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain import JsonValue
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

_ANNOTATIONS = TypeAdapter(list[dict[str, JsonValue]])
_PERMANENT_SYNC_SOURCE_ERRORS = frozenset(
    {"zotero_item_not_found", "zotero_attachment_not_found"}
)


def _library_import_state(
    item: object | None,
) -> Literal["available", "imported", "in_progress", "failed"]:
    if item is None:
        return "available"
    status = getattr(item, "status", None)
    if status == ZoteroImportStatus.COMPLETED:
        return "imported"
    if status in {ZoteroImportStatus.PENDING, ZoteroImportStatus.PROCESSING}:
        return "in_progress"
    return "failed"


class DefaultZoteroGateway:
    def __init__(
        self,
        db: Session,
        *,
        connections: ZoteroConnectionRepository,
    ) -> None:
        self._db = db
        self._connections = connections

    def save_oauth_request(
        self,
        *,
        user_id: int,
        request_token: ZoteroRequestToken,
        return_path: str,
        intent: str,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> None:
        self._connections.create_pending(
            user_id=user_id,
            oauth_token=request_token.token,
            oauth_token_secret=request_token.secret,
            return_path=return_path,
            intent=intent,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
        )

    def consume_oauth_callback(
        self,
        *,
        oauth_token: str,
    ) -> PreparedZoteroCallback | None:
        pending = self._connections.get_pending_by_token(oauth_token=oauth_token)
        if pending is None or pending.user_id is None:
            return None
        expires_at = pending.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        callback = PreparedZoteroCallback(
            user_id=pending.user_id,
            request_token=ZoteroRequestToken(
                token=oauth_token,
                secret=self._connections.pending_secret(pending=pending),
            ),
            expires_at=expires_at,
            correlation_id=pending.correlation_id,
            origin_operation_id=pending.origin_operation_id,
            return_path=pending.return_path,
            intent=pending.intent,
        )
        self._connections.delete_pending(pending=pending)
        return callback

    def save_connection(
        self,
        *,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> ZoteroConnectionChange:
        upsert = self._connections.upsert_connection(
            user_id=callback.user_id,
            zotero_user_id=access_token.user_id,
            api_key=access_token.api_key,
            now=datetime.now(UTC),
        )
        return ZoteroConnectionChange(
            connection_revision=upsert.connection.credential_revision,
            changed=upsert.changed,
        )

    def status(self, *, actor: Actor) -> ZoteroConnectionStatus:
        connection = self._connections.get_by_user_id(user_id=actor.id)
        if connection is None:
            return ZoteroConnectionStatus(
                connection_state="disconnected",
                automatic_annotation_sync="off",
            )
        try:
            credentials_readable = (
                self._connections.credentials(user_id=actor.id) is not None
            )
        except ValueError:
            credentials_readable = False
        eligible = can_user_auto_sync_zotero(self._db, actor)
        enabled = connection.configuration.get("auto_import_enabled") is True
        last_error_code = (
            connection.last_error_code
            if credentials_readable
            else "integration_credentials_unreadable"
        )
        return ZoteroConnectionStatus(
            connection_state=("invalid" if last_error_code else "connected"),
            connected_at=connection.created_at,
            last_successful_sync_at=(
                datetime.fromisoformat(str(connection.configuration["last_sync_at"]))
                if connection.configuration.get("last_sync_at")
                else zotero_import_repository.get_max_last_synced_at(
                    self._db,
                    user_id=actor.id,
                )
            ),
            automatic_sync_eligible=eligible,
            automatic_annotation_sync="active" if eligible else "off",
            auto_import_enabled=enabled,
            auto_import_state=("active" if eligible else "paused")
            if enabled
            else "off",
            last_error_code=last_error_code,
        )

    def credential_revision_is_current(
        self,
        *,
        user_id: int,
        revision: UUID,
    ) -> bool:
        return self._connections.credential_revision_is_current(
            user_id=user_id,
            revision=revision,
        )

    def set_sync_preferences(
        self,
        *,
        actor: Actor,
        request: ZoteroSyncPreferencesRequest,
        library_version: int | None,
    ) -> ZoteroConnectionStatus:
        connection = self._connections.get_by_user_id(user_id=actor.id)
        if connection is None:
            raise AppError(
                code="zotero_not_connected",
                message="Zotero is not connected",
                kind=FailureKind.CONFLICT,
            )
        if request.auto_import_enabled and not can_user_auto_sync_zotero(
            self._db, actor
        ):
            raise AppError(
                code="zotero_auto_import_requires_researcher",
                message="Automatic Zotero import requires Researcher access",
                kind=FailureKind.PERMISSION_DENIED,
            )
        configuration = dict(connection.configuration)
        configuration["auto_import_enabled"] = request.auto_import_enabled
        if request.auto_import_enabled:
            if library_version is None:
                raise AppError(
                    code="zotero_unavailable",
                    message="The Zotero library checkpoint is unavailable",
                    kind=FailureKind.DEPENDENCY_FAILURE,
                    retryable=True,
                )
            configuration["auto_import_library_version"] = library_version
            configuration["auto_import_start"] = 0
        self._connections.update_configuration(
            user_id=actor.id,
            configuration=configuration,
            now=datetime.now(UTC),
        )
        return self.status(actor=actor)

    def disconnect(self, *, user_id: int) -> UUID | None:
        return self._connections.delete_by_user_id(user_id=user_id)

    def credentials(
        self,
        *,
        user_id: int,
        lock: bool = False,
    ) -> ZoteroCredentials | None:
        resolved = self._connections.credentials(user_id=user_id, lock=lock)
        if resolved is None:
            return None
        zotero_user_id, api_key, revision = resolved
        return ZoteroCredentials(
            user_id=zotero_user_id,
            api_key=api_key,
            revision=revision,
        )

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryPage:
        imported_rows = zotero_import_repository.list_by_item_keys(
            self._db,
            user_id=actor.id,
            item_keys=[item.item_key for item in snapshot.items],
        )
        imported_by_key = {row.zotero_item_key: row for row, _title in imported_rows}
        return ZoteroLibraryPage(
            items=[
                ZoteroLibraryItem(
                    zotero_item_key=item.item_key,
                    title=item.title,
                    authors=list(item.authors),
                    date=item.publish_date,
                    item_type=item.item_type,
                    venue=item.venue,
                    date_added=item.date_added,
                    tags=list(item.tags),
                    collection_keys=list(item.collection_keys),
                    import_state=_library_import_state(
                        imported_by_key.get(item.item_key)
                    ),
                    source_availability=(
                        "stored_pdf"
                        if item.has_pdf_attachment
                        else "resolvable_source"
                        if item.has_resolvable_source
                        else "unavailable"
                    ),
                )
                for item in snapshot.items
            ],
            previous_cursor=str(max(0, snapshot.start - snapshot.limit))
            if snapshot.start > 0
            else None,
            next_cursor=str(snapshot.start + snapshot.limit)
            if snapshot.start + len(snapshot.items) < snapshot.total_count
            else None,
            total_count=snapshot.total_count,
            remaining_slots=get_remaining_paper_upload_slots(
                self._db,
                actor,
            ),
        )

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
        credential_revision: UUID,
    ) -> ZoteroImportPlan:
        self._require_current_revision(
            user_id=actor.id,
            credential_revision=credential_revision,
        )
        can_upload, _upload_error = can_user_upload_paper(self._db, actor)
        remaining = (
            get_remaining_paper_upload_slots(self._db, actor) if can_upload else 0
        )
        plans: list[ZoteroImportPlanItem] = []
        errors: list[ZoteroImportError] = []
        skipped_item_keys: list[str] = []
        skipped = 0
        claimed_doi: dict[str, str] = {}
        candidate_count = 0

        for item in items:
            if not item.has_metadata:
                skipped_item_keys.append(item.item_key)
                skipped += 1
                continue
            existing = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=actor.id,
                zotero_item_key=item.item_key,
            )
            if (
                existing is not None
                and existing.status == ZoteroImportStatus.COMPLETED
                and existing.document_id is not None
                and document_repository.find_accessible(
                    self._db,
                    document_id=existing.document_id,
                    user=actor,
                )
                is not None
            ):
                skipped += 1
                skipped_item_keys.append(item.item_key)
                continue

            doi = normalize_doi(item.doi)
            if doi:
                document = document_repository.find_library_document_by_doi(
                    self._db,
                    user_id=actor.id,
                    doi=doi,
                )
                if document is not None:
                    plans.append(
                        ZoteroImportPlanItem(
                            item=item,
                            disposition="link_existing",
                            document_id=document.id,
                            document_source_key=document.s3_object_key,
                        )
                    )
                    skipped += 1
                    continue
                source_item_key = claimed_doi.get(doi)
                if source_item_key is not None:
                    plans.append(
                        ZoteroImportPlanItem(
                            item=item,
                            disposition="link_batch",
                            source_item_key=source_item_key,
                        )
                    )
                    skipped += 1
                    continue

            if candidate_count >= remaining:
                errors.append(
                    ZoteroImportError(
                        zotero_item_key=item.item_key,
                        error="zotero_quota_exceeded",
                    )
                )
                continue
            plans.append(ZoteroImportPlanItem(item=item, disposition="import"))
            candidate_count += 1
            if doi:
                claimed_doi[doi] = item.item_key

        return ZoteroImportPlan(
            items=tuple(plans),
            skipped_already_imported=skipped,
            errors=tuple(errors),
            skipped_item_keys=tuple(skipped_item_keys),
        )

    def reserve_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID,
        credential_revision: UUID,
    ) -> UUID:
        self._require_current_revision(
            user_id=user_id,
            credential_revision=credential_revision,
        )
        existing = zotero_import_repository.get_by_item_key(
            self._db,
            user_id=user_id,
            zotero_item_key=item_key,
        )
        if existing is not None:
            if (
                existing.status == ZoteroImportStatus.COMPLETED
                and existing.document_id is not None
            ):
                raise AppError(
                    code="zotero_item_already_imported",
                    message="The Zotero item has already been imported",
                    kind=FailureKind.CONFLICT,
                )
            self._db.delete(existing)
            self._db.flush()
        created = zotero_import_repository.create(
            self._db,
            user_id=user_id,
            zotero_item_key=item_key,
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            upload_job_id=upload_job_id,
            status=ZoteroImportStatus.PROCESSING,
        )
        return created.id

    def fail_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
        credential_revision: UUID,
    ) -> ZoteroItemMutation:
        self._require_current_revision(
            user_id=user_id,
            credential_revision=credential_revision,
        )
        imported_item = (
            zotero_import_repository.get_by_upload_job_id(
                self._db,
                upload_job_id=upload_job_id,
            )
            if upload_job_id is not None
            else None
        )
        if imported_item is None:
            imported_item = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=user_id,
                zotero_item_key=item_key,
            )
        if imported_item is None:
            imported_item = zotero_import_repository.create(
                self._db,
                user_id=user_id,
                zotero_item_key=item_key,
                import_source=ZoteroImportSource.PDF_ATTACHMENT,
                upload_job_id=upload_job_id,
                status=ZoteroImportStatus.FAILED,
            )
            imported_item.error_message = error_code
            self._db.flush()
            return ZoteroItemMutation(
                imported_item_id=imported_item.id,
                changed=True,
            )
        if imported_item.user_id != user_id:
            raise AppError(
                code="zotero_import_access_denied",
                message="Zotero import access denied",
                kind=FailureKind.PERMISSION_DENIED,
            )
        change = zotero_import_repository.update_status(
            self._db,
            item=imported_item,
            status=ZoteroImportStatus.FAILED,
            error_message=error_code,
        )
        return ZoteroItemMutation(
            imported_item_id=imported_item.id,
            changed=change.changed,
        )

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
    ) -> ZoteroImportMutation:
        self._require_current_revision(
            user_id=actor.id,
            credential_revision=credential_revision,
        )
        imported_item = zotero_import_repository.get_by_upload_job_id(
            self._db,
            upload_job_id=upload_job_id,
        )
        if imported_item is None or imported_item.user_id != actor.id:
            raise AppError(
                code="zotero_import_not_found",
                message="Zotero import not found",
                kind=FailureKind.NOT_FOUND,
            )
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            raise RuntimeError("zotero_canonical_document_missing")
        self._apply_metadata(document=document, item=item, actor=actor)
        self._apply_tags(document_id=document_id, tags=item.tags, actor=actor)
        annotations = self._annotations(attachment.annotations_json)
        finalized = zotero_import_repository.finalize_processing_import(
            self._db,
            item=imported_item,
            import_source=attachment.import_source,
            zotero_attachment_key=attachment.attachment_key,
            source_url=attachment.source_url,
            document_id=document_id,
            upload_job_id=upload_job_id,
            annotations_payload=annotations or None,
            zotero_item_version=item.version,
            zotero_attachment_version=attachment.version,
        )
        completed = reused_document
        changed = finalized.changed
        if reused_document:
            applied = (
                apply_annotation_snapshot(
                    self._db,
                    document_id=document_id,
                    user=actor,
                    annotations_payload=annotations,
                    page_dimensions=page_dimensions,
                )
                if annotations
                else 0
            )
            status = zotero_import_repository.update_status(
                self._db,
                item=imported_item,
                status=ZoteroImportStatus.COMPLETED,
                document_id=document_id,
            )
            changed = changed or status.changed or applied > 0
        return ZoteroImportMutation(
            imported_item_id=imported_item.id,
            result=self._import_result(
                item=item,
                attachment=attachment,
                document_id=document_id,
                upload_job_id=upload_job_id,
            ),
            changed=changed,
            completed=completed,
        )

    def link_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
        credential_revision: UUID,
    ) -> ZoteroImportMutation:
        self._require_current_revision(
            user_id=actor.id,
            credential_revision=credential_revision,
        )
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        existing = zotero_import_repository.get_by_item_key(
            self._db,
            user_id=actor.id,
            zotero_item_key=item.item_key,
        )
        if (
            existing is not None
            and existing.status == ZoteroImportStatus.COMPLETED
            and existing.document_id == document_id
        ):
            return ZoteroImportMutation(
                imported_item_id=existing.id,
                result=self._import_result(
                    item=item,
                    attachment=attachment,
                    document_id=document_id,
                    upload_job_id=None,
                ),
                changed=False,
                completed=True,
            )
        if existing is not None:
            self._db.delete(existing)
            self._db.flush()
        annotations = self._annotations(attachment.annotations_json)
        imported_item = zotero_import_repository.create(
            self._db,
            user_id=actor.id,
            zotero_item_key=item.item_key,
            import_source=attachment.import_source,
            zotero_attachment_key=attachment.attachment_key,
            source_url=attachment.source_url,
            document_id=document_id,
            annotations_payload=annotations or None,
            status=ZoteroImportStatus.COMPLETED,
            last_synced_at=datetime.now(timezone.utc),
            zotero_item_version=item.version,
            zotero_attachment_version=attachment.version,
        )
        if annotations:
            apply_annotation_snapshot(
                self._db,
                document_id=document_id,
                user=actor,
                annotations_payload=annotations,
                page_dimensions=page_dimensions,
            )
        return ZoteroImportMutation(
            imported_item_id=imported_item.id,
            result=self._import_result(
                item=item,
                attachment=attachment,
                document_id=document_id,
                upload_job_id=None,
            ),
            changed=True,
            completed=True,
        )

    def sync_targets(
        self,
        *,
        user_id: int,
        limit: int,
        credential_revision: UUID,
    ) -> tuple[ZoteroSyncTarget, ...]:
        self._require_current_revision(
            user_id=user_id,
            credential_revision=credential_revision,
        )
        return tuple(
            ZoteroSyncTarget(
                imported_item_id=row.id,
                item_key=row.zotero_item_key,
                document_id=row.document_id,
                attachment_key=row.zotero_attachment_key,
                document_source_key=document.s3_object_key,
            )
            for row in zotero_import_repository.list_syncable_by_user(
                self._db,
                user_id=user_id,
                limit=limit,
            )
            if row.document_id is not None
            and row.zotero_attachment_key is not None
            and (document := self._db.get(Document, row.document_id)) is not None
        )

    def apply_sync(
        self,
        *,
        actor: Actor,
        batch: ZoteroSyncBatch,
        credential_revision: UUID,
    ) -> ZoteroSyncMutation:
        self._require_current_revision(
            user_id=actor.id,
            credential_revision=credential_revision,
        )
        synced_documents: set[UUID] = set()
        changed_documents: set[UUID] = set()
        new_annotations = 0
        synced_at = datetime.now(timezone.utc)
        for failure in batch.failures:
            imported_item = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=actor.id,
                zotero_item_key=failure.item_key,
            )
            if imported_item is None:
                continue
            zotero_import_repository.update_after_sync_failure(
                self._db,
                item=imported_item,
                error_code=failure.error_code,
                attempted_at=synced_at,
                source_unavailable=(
                    failure.error_code in _PERMANENT_SYNC_SOURCE_ERRORS
                ),
            )
        for update in batch.updates:
            target = update.target
            imported_item = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=actor.id,
                zotero_item_key=target.item_key,
            )
            if (
                imported_item is None
                or imported_item.id != target.imported_item_id
                or imported_item.document_id != target.document_id
            ):
                continue
            document = document_repository.find_accessible(
                self._db,
                document_id=target.document_id,
                user=actor,
            )
            if document is None:
                continue
            annotations = self._annotations(update.annotations_json)
            applied = (
                apply_annotation_snapshot(
                    self._db,
                    document_id=target.document_id,
                    user=actor,
                    annotations_payload=annotations,
                    page_dimensions=update.page_dimensions,
                )
                if annotations
                else 0
            )
            zotero_import_repository.update_after_sync(
                self._db,
                item=imported_item,
                annotations_payload=annotations or None,
                last_synced_at=synced_at,
            )
            synced_documents.add(target.document_id)
            new_annotations += applied
            if applied:
                changed_documents.add(target.document_id)
        return ZoteroSyncMutation(
            response=ZoteroSyncResponse(
                synced_papers_count=len(synced_documents),
                new_annotations_count=new_annotations,
            ),
            changed_document_ids=tuple(sorted(changed_documents, key=str)),
        )

    def auto_import_cursor(self, *, user_id: int) -> ZoteroAutoImportCursor | None:
        connection = self._connections.get_by_user_id(user_id=user_id)
        if (
            connection is None
            or connection.configuration.get("auto_import_enabled") is not True
        ):
            return None
        version = connection.configuration.get("auto_import_library_version")
        if not isinstance(version, int) or isinstance(version, bool):
            return None
        start = connection.configuration.get("auto_import_start")
        return ZoteroAutoImportCursor(
            library_version=version,
            start=(
                start
                if isinstance(start, int) and not isinstance(start, bool) and start >= 0
                else 0
            ),
        )

    def advance_sync_checkpoint(
        self,
        *,
        user_id: int,
        credential_revision: UUID,
        library_version: int | None,
        auto_import_cursor: ZoteroAutoImportCursor | None,
    ) -> bool:
        try:
            self._require_current_revision(
                user_id=user_id,
                credential_revision=credential_revision,
            )
        except AppError as exc:
            if exc.code == "zotero_credentials_rotated":
                return False
            raise
        connection = self._connections.get_by_user_id(user_id=user_id, lock=True)
        assert connection is not None
        configuration = dict(connection.configuration)
        configuration["last_sync_at"] = datetime.now(UTC).isoformat()
        if library_version is not None:
            configuration["last_sync_library_version"] = library_version
        if (
            auto_import_cursor is not None
            and configuration.get("auto_import_enabled") is True
        ):
            configuration["auto_import_library_version"] = (
                auto_import_cursor.library_version
            )
            configuration["auto_import_start"] = auto_import_cursor.start
        self._connections.update_configuration(
            user_id=user_id,
            configuration=configuration,
            now=datetime.now(UTC),
        )
        return True

    def _require_current_revision(
        self,
        *,
        user_id: int,
        credential_revision: UUID,
    ) -> None:
        if not self._connections.credential_revision_is_current(
            user_id=user_id,
            revision=credential_revision,
            lock=True,
        ):
            raise AppError(
                code="zotero_credentials_rotated",
                message="The Zotero connection changed before this result was applied",
                kind=FailureKind.CONFLICT,
            )

    def _apply_metadata(
        self,
        *,
        document: Document,
        item: ZoteroItemSnapshot,
        actor: Actor,
    ) -> None:
        document_repository.update_canonical(
            self._db,
            document=document,
            update=DocumentUpdate(
                title=item.title or None,
                authors=list(item.authors) or None,
                abstract=item.abstract,
                publish_date=item.publish_date,
                doi=item.doi,
            ),
            user=actor,
        )

    def _apply_tags(
        self,
        *,
        document_id: UUID,
        tags: tuple[str, ...],
        actor: Actor,
    ) -> None:
        for name in tags:
            tag = library_tag_repository.get_or_create(
                self._db,
                user_id=actor.id,
                name=name,
            )
            library_tag_repository.assign_to_document(
                self._db,
                user_id=actor.id,
                document_id=document_id,
                tag_id=tag.id,
            )

    @staticmethod
    def _annotations(value: str) -> list[dict[str, JsonValue]]:
        if not value:
            return []
        return _ANNOTATIONS.validate_python(json.loads(value))

    @staticmethod
    def _import_result(
        *,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        upload_job_id: UUID | None,
    ) -> ZoteroImportItemResult:
        return ZoteroImportItemResult(
            zotero_item_key=item.item_key,
            document_id=str(document_id),
            upload_job_id=str(upload_job_id) if upload_job_id is not None else None,
            import_source=attachment.import_source,
            title=item.title or None,
        )
