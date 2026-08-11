"""Prepare/external/finalize workflow for paper ingestion."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.s3 import s3_service
from app.helpers.s3 import document_source_key
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.modules.papers.application.ingestion import PdfUrlSource, PreparedPaperInput
from app.modules.papers.domain import content_sha256
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
    async def resolve(self, *, kind: str, value: str) -> str: ...


class PaperIngestionWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        url_source: PdfUrlSource,
        source_resolver: PaperSourceResolver,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._url_source = url_source
        self._source_resolver = source_resolver
        self._operation_factory = operation_factory

    async def from_url(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        url: str,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> UploadAcceptedResponse:
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_url(
            actor=actor,
            url=url,
            source=self._url_source,
            ip_address=ip_address,
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
    ) -> UploadAcceptedResponse:
        url = await self._source_resolver.resolve(kind=kind, value=value)
        try:
            return await self.from_url(
                actor=actor,
                operation=operation,
                url=url,
                project_id=project_id,
                idempotency_key=idempotency_key,
                ip_address=ip_address,
            )
        except AppError as error:
            if error.code in {"invalid_pdf_url", "invalid_pdf"}:
                raise AppError(
                    code="paper_source_pdf_unavailable",
                    message="No safely accessible PDF is available for this source",
                    kind=FailureKind.INVALID_ARGUMENT,
                ) from error
            raise

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
    ) -> UploadAcceptedResponse:
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

    async def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        idempotency_key: str | None,
    ) -> UploadAcceptedResponse:
        retry_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        reservation = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.retry(
                actor=actor,
                operation=retry_operation,
                job_id=job_id,
                idempotency_key=idempotency_key,
            )
        )
        if reservation.replayed:
            return UploadAcceptedResponse(job_id=reservation.job_id)
        try:
            content = await asyncio.to_thread(
                s3_service.download_bytes,
                document_source_key(reservation.content_sha256),
            )
        except RuntimeError as error:
            self._fail(
                actor=actor,
                operation=retry_operation,
                job_id=reservation.job_id,
                error_code="paper_source_pdf_unavailable",
            )
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
            filename=reservation.filename,
        )
        return await self._dispatch_reserved(
            actor=actor,
            operation=retry_operation,
            prepared=prepared,
            job_id=reservation.job_id,
        )

    async def _start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> UploadAcceptedResponse:
        reserve_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        reservation = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.reserve(
                actor=actor,
                operation=reserve_operation,
                prepared=prepared,
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
        )
        if reservation.replayed:
            return UploadAcceptedResponse(job_id=reservation.job_id)

        return await self._dispatch_reserved(
            actor=actor,
            operation=reserve_operation,
            prepared=prepared,
            job_id=reservation.job_id,
        )

    async def _dispatch_reserved(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        job_id: UUID,
    ) -> UploadAcceptedResponse:

        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        try:
            await ingestion.acquire(actor=actor, job_id=job_id)
            digest = content_sha256(prepared.content)
            await asyncio.to_thread(
                s3_service.upload_document_source,
                sha256=digest,
                pdf_bytes=prepared.content,
            )
            finalize_operation = self._operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            finalization = self._executor.command(
                lambda capabilities: capabilities.paper_ingestion.finalize(
                    actor=actor,
                    operation=finalize_operation,
                    job_id=job_id,
                    prepared=prepared,
                )
            )
            if finalization.job_completed:
                await ingestion.release(actor=actor, job_id=job_id)
            track_event(
                "paper_upload_submitted_to_microservice",
                properties={"task_id": finalization.task_id},
                user_id=str(actor.id),
            )
            return UploadAcceptedResponse(job_id=job_id)
        except AppError as exc:
            self._fail(
                actor=actor,
                operation=operation,
                job_id=job_id,
                error_code=exc.code,
            )
            await ingestion.release(actor=actor, job_id=job_id)
            raise
        except Exception as exc:
            logger.error("paper_ingestion.job_submission.failed", exc_info=True)
            self._fail(
                actor=actor,
                operation=operation,
                job_id=job_id,
                error_code="jobs_submission_failed",
            )
            await ingestion.release(actor=actor, job_id=job_id)
            raise AppError(
                code="jobs_submission_failed",
                message="The document processing job could not be started",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    def _fail(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        error_code: str,
    ) -> None:
        fail_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.fail(
                actor=actor,
                operation=fail_operation,
                job_id=job_id,
                error_code=error_code,
            )
        )
