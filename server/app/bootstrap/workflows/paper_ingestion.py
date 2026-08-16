"""Atomic PDF-ingestion orchestration around external storage I/O."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.s3 import document_source_key, s3_service
from app.modules.jobs.infrastructure.client import JobsClient
from app.modules.papers.application.contracts.documents import (
    LibraryPaperIngestionResponse,
)
from app.modules.papers.application.ingestion import PdfUrlSource, PreparedPaperInput
from app.modules.papers.domain import MAX_PDF_BYTES, content_sha256
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind

logger = logging.getLogger(__name__)


class PaperSourceResolver(Protocol):
    async def resolve(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        kind: str,
        value: str,
    ) -> str: ...


class PaperIngestionWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        url_source: PdfUrlSource,
        source_resolver: PaperSourceResolver,
        operation_factory: OperationContextFactory,
        jobs: JobsClient,
    ) -> None:
        self._executor = executor
        self._url_source = url_source
        self._source_resolver = source_resolver
        self._operation_factory = operation_factory
        self._jobs = jobs

    async def from_url(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        url: str,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_url(
            actor=actor,
            url=url,
            source=self._url_source,
            ip_address=ip_address,
            display_name=self._url_display_name(url),
            source_kind="url",
        )
        return await self._start(
            actor=actor,
            operation=operation,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def from_source(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        kind: str,
        value: str,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        url = await self._source_resolver.resolve(
            actor=actor,
            operation=operation,
            kind=kind,
            value=value,
        )
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_url(
            actor=actor,
            url=url,
            source=self._url_source,
            ip_address=ip_address,
            display_name=self._source_display_name(kind=kind, value=value),
            source_kind=kind,
        )
        return await self._start(
            actor=actor,
            operation=operation,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def from_bytes(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        content: bytes,
        filename: str | None,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_bytes(
            actor=actor,
            content=content,
            filename=filename,
            ip_address=ip_address,
        )
        return await self._start(
            actor=actor,
            operation=operation,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def from_upload_session(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        upload_id: UUID,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        """Validate staged bytes and ingest them through the canonical byte path."""
        record = self._executor.command(
            lambda capabilities: capabilities.paper_uploads.claim(
                actor=actor,
                upload_id=upload_id,
            )
        )
        lease_token = record.lease_token
        assert lease_token is not None
        try:
            if record.project_id != project_id:
                raise AppError(
                    code="paper_upload_project_mismatch",
                    message=(
                        "The ingestion Project must match the Project bound when the "
                        "upload was prepared"
                    ),
                    kind=FailureKind.CONFLICT,
                )
            try:
                staging_metadata = await asyncio.to_thread(
                    s3_service.staging_object_metadata,
                    record.object_key,
                )
            except FileNotFoundError as exc:
                raise AppError(
                    code="paper_upload_not_completed",
                    message="No PDF bytes were uploaded for this upload session",
                    kind=FailureKind.CONFLICT,
                ) from exc
            if staging_metadata.size_bytes != record.size_bytes:
                raise AppError(
                    code="paper_upload_size_mismatch",
                    message="The uploaded PDF size does not match the prepared file",
                    kind=FailureKind.UNPROCESSABLE,
                    details={
                        "expected_size_bytes": record.size_bytes,
                        "actual_size_bytes": staging_metadata.size_bytes,
                    },
                )
            expected_checksum = base64.b64encode(bytes.fromhex(record.sha256)).decode()
            if staging_metadata.checksum_sha256 != expected_checksum:
                raise AppError(
                    code="paper_upload_checksum_mismatch",
                    message="The uploaded PDF checksum does not match the prepared file",
                    kind=FailureKind.UNPROCESSABLE,
                )
            content = await asyncio.to_thread(
                s3_service.download_staging_bytes,
                record.object_key,
                metadata=staging_metadata,
                max_bytes=MAX_PDF_BYTES,
            )
            if hashlib.sha256(content).hexdigest() != record.sha256:
                raise AppError(
                    code="paper_upload_checksum_mismatch",
                    message="The downloaded PDF checksum does not match the prepared file",
                    kind=FailureKind.UNPROCESSABLE,
                )
            result = await self.from_bytes(
                actor=actor,
                operation=operation,
                content=content,
                filename=record.filename,
                project_id=record.project_id,
                idempotency_key=idempotency_key or f"upload-session:{upload_id}",
                ip_address=ip_address,
            )
            self._executor.command(
                lambda capabilities: capabilities.paper_uploads.consume(
                    actor=actor,
                    upload_id=upload_id,
                    lease_token=lease_token,
                )
            )
        except AppError as exc:
            failed = exc.kind in {
                FailureKind.INVALID_ARGUMENT,
                FailureKind.PAYLOAD_TOO_LARGE,
                FailureKind.UNPROCESSABLE,
            }
            self._executor.command(
                lambda capabilities: capabilities.paper_uploads.release(
                    actor=actor,
                    upload_id=upload_id,
                    lease_token=lease_token,
                    failed=failed,
                )
            )
            raise
        except Exception as exc:
            self._executor.command(
                lambda capabilities: capabilities.paper_uploads.release(
                    actor=actor,
                    upload_id=upload_id,
                    lease_token=lease_token,
                    failed=False,
                )
            )
            raise AppError(
                code="paper_upload_unavailable",
                message="The staged PDF could not be read",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        await asyncio.to_thread(s3_service.delete_file, record.object_key)
        return result

    async def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        idempotency_key: str | None,
    ) -> LibraryPaperIngestionResponse:
        retry_source = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion.retry_source(
                actor=actor,
                job_id=job_id,
            )
        )
        try:
            content = await asyncio.to_thread(
                s3_service.download_bytes,
                document_source_key(retry_source.content_sha256),
            )
        except RuntimeError as error:
            raise AppError(
                code="paper_source_pdf_unavailable",
                message="The persisted PDF source is unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from error
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = ingestion.prepare_persisted(
            content=content,
            filename=retry_source.filename,
            display_name=retry_source.display_name,
            source_kind=retry_source.source_kind,
        )
        return await self._start(
            actor=actor,
            operation=operation,
            prepared=prepared,
            project_id=retry_source.project_id,
            idempotency_key=idempotency_key,
            retry_of=job_id,
        )

    async def cancel(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
    ) -> None:
        cancel_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        changed = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.cancel(
                actor=actor,
                operation=cancel_operation,
                job_id=job_id,
            )
        )
        if changed:
            ingestion = self._executor.query(
                lambda capabilities: capabilities.paper_ingestion
            )
            await ingestion.release(actor=actor, job_id=job_id)

    async def _start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
        retry_of: UUID | None = None,
    ) -> LibraryPaperIngestionResponse:
        proposed_job_id = uuid4()
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        acquired = False
        accepted_job_id: UUID | None = None
        try:
            await ingestion.acquire(actor=actor, job_id=proposed_job_id)
            acquired = True
            digest = content_sha256(prepared.content)
            await asyncio.to_thread(
                s3_service.upload_document_source,
                sha256=digest,
                pdf_bytes=prepared.content,
            )
            accept_operation = self._operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            accepted = self._executor.command(
                lambda capabilities: capabilities.paper_ingestion.accept(
                    actor=actor,
                    operation=accept_operation,
                    prepared=prepared,
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    job_id=proposed_job_id,
                    retry_of=retry_of,
                )
            )
            accepted_job_id = accepted.ingestion.id
            if (
                accepted.replayed
                or accepted_job_id != proposed_job_id
                or not accepted.processing_required
            ):
                await ingestion.release(actor=actor, job_id=proposed_job_id)
                acquired = False
            track_event(
                "paper_upload_submitted_to_microservice",
                properties={"task_id": str(accepted_job_id)},
                user_id=str(actor.id),
            )
            return accepted.ingestion
        except AppError:
            if acquired:
                await ingestion.release(actor=actor, job_id=proposed_job_id)
            raise
        except Exception as exc:
            logger.error("paper_ingestion.accept.failed", exc_info=True)
            if acquired:
                await ingestion.release(actor=actor, job_id=proposed_job_id)
            raise AppError(
                code="jobs_submission_failed",
                message="The document processing job could not be started",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    @staticmethod
    def _source_display_name(*, kind: str, value: str) -> str:
        normalized = value.strip()
        if kind == "arxiv":
            return f"arXiv {normalized}"
        if kind == "doi":
            return f"DOI {normalized}"
        return PaperIngestionWorkflow._url_display_name(normalized)

    @staticmethod
    def _url_display_name(url: str) -> str:
        filename = PurePosixPath(unquote(urlparse(url).path)).name
        return filename or "PDF URL"
