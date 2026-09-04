"""Atomic PDF-ingestion orchestration around external storage I/O."""

from __future__ import annotations

import asyncio
import base64
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
from app.modules.papers.domain import content_sha256, normalize_doi
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
        add_to_library: bool = True,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        await ingestion.enforce_rate(actor=actor, ip_address=ip_address)
        normalized_url = url.strip()
        parsed_url = urlparse(normalized_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise AppError(
                code="paper_source_pdf_unavailable",
                message="No safely accessible PDF is available for this source",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return await self._start_source(
            actor=actor,
            operation=operation,
            kind="url",
            fingerprint=self._source_fingerprint("url", normalized_url),
            resolved_url=normalized_url,
            filename=None,
            display_name=self._url_display_name(normalized_url),
            project_id=project_id,
            add_to_library=add_to_library,
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
        add_to_library: bool = True,
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
        await ingestion.enforce_rate(actor=actor, ip_address=ip_address)
        fingerprint = self._source_fingerprint(kind, value)
        return await self._start_source(
            actor=actor,
            operation=operation,
            kind=kind,
            fingerprint=fingerprint,
            resolved_url=url,
            filename=None,
            display_name=self._source_display_name(kind=kind, value=value),
            project_id=project_id,
            add_to_library=add_to_library,
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
        add_to_library: bool = True,
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
            add_to_library=add_to_library,
            idempotency_key=idempotency_key,
        )

    async def from_upload_session(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        upload_id: UUID,
        project_id: UUID | None,
        add_to_library: bool = True,
        idempotency_key: str | None,
        ip_address: str,
    ) -> LibraryPaperIngestionResponse:
        """Validate staged metadata and let the document worker read the object."""
        del ip_address
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
            if record.add_to_library != add_to_library:
                raise AppError(
                    code="paper_upload_metadata_mismatch",
                    message=(
                        "The ingestion add_to_library must match the upload preparation"
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
            result = await self._start_source(
                actor=actor,
                operation=operation,
                kind="upload",
                fingerprint=f"upload:{upload_id}",
                resolved_url=None,
                filename=record.filename,
                display_name=record.filename,
                upload_id=upload_id,
                upload_object_key=record.object_key,
                project_id=record.project_id,
                add_to_library=record.add_to_library,
                idempotency_key=idempotency_key or f"upload-session:{upload_id}",
                expected_sha256=record.sha256,
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
            add_to_library=retry_source.add_to_library,
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
            await self.release_cancelled(actor=actor, job_id=job_id)

    async def release_cancelled(self, *, actor: Actor, job_id: UUID) -> None:
        """Release only the external concurrency lease after DB cancellation commits."""
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
        add_to_library: bool = True,
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
                    add_to_library=add_to_library,
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

    async def _start_source(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        kind: str,
        fingerprint: str,
        resolved_url: str | None,
        filename: str | None,
        display_name: str,
        project_id: UUID | None,
        add_to_library: bool,
        idempotency_key: str | None,
        upload_id: UUID | None = None,
        upload_object_key: str | None = None,
        expected_sha256: str | None = None,
    ) -> LibraryPaperIngestionResponse:
        proposed_job_id = uuid4()
        accepted = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.accept_source(
                actor=actor,
                operation=operation,
                project_id=project_id,
                add_to_library=add_to_library,
                filename=filename,
                display_name=display_name,
                source_kind=kind,
                fingerprint=fingerprint,
                resolved_url=resolved_url,
                upload_id=upload_id,
                upload_object_key=upload_object_key,
                expected_sha256=expected_sha256,
                idempotency_key=idempotency_key,
                job_id=proposed_job_id,
            )
        )
        if not accepted.processing_required:
            return accepted.ingestion
        track_event(
            "paper_upload_submitted_to_microservice",
            properties={"task_id": str(accepted.ingestion.id), "source_kind": kind},
            user_id=str(actor.id),
        )
        return accepted.ingestion

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

    @staticmethod
    def _source_fingerprint(kind: str, value: str) -> str:
        normalized = value.strip().casefold()
        if kind == "arxiv":
            normalized = normalized.removeprefix("arxiv:").strip("/")
        elif kind == "doi":
            normalized = normalize_doi(normalized) or normalized.removeprefix(
                "https://doi.org/"
            )
        return f"{kind}:{normalized}"
