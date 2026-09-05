"""Short-transaction PDF post-processing continuation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.jobs.application.callbacks import (
    JobCompletionResult,
    PdfPostprocessResolution,
)
from app.modules.jobs.application.contracts import PdfPostprocessCallback
from app.modules.papers.application.citations import CitationMetadataPatch
from app.modules.papers.domain.citations import (
    CitationFields,
    bibliographic_gaps,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind
from pydantic import ValidationError
from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    PassageEmbeddingRecord,
    decode_passage_embedding_artifact,
)

from app.helpers.s3 import s3_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PdfPostprocessSnapshot:
    terminal: bool
    fields: CitationFields | None


class PdfPostprocessReader(Protocol):
    def read(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        callback_task_id: UUID,
    ) -> PdfPostprocessSnapshot: ...


class PdfPostprocessWorkflow:
    """Read facts, resolve metadata without a Session, then atomically apply."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        reader: PdfPostprocessReader,
        provider: CitationMetadataProvider,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._reader = reader
        self._provider = provider
        self._operation_factory = operation_factory

    async def complete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        payload: dict[str, object],
    ) -> JobCompletionResult:
        try:
            callback = PdfPostprocessCallback.model_validate(payload)
        except ValidationError as exc:
            raise AppError(
                code="job_callback_invalid",
                message="Job callback payload is invalid for its operation",
                kind=FailureKind.UNPROCESSABLE,
            ) from exc

        snapshot = self._reader.read(
            actor=actor,
            job_id=job_id,
            callback_task_id=callback.task_id,
        )
        metadata_resolution = (
            PdfPostprocessResolution()
            if snapshot.terminal
            else await asyncio.to_thread(
                self._resolve_external,
                actor,
                operation,
                _require_fields(snapshot),
            )
        )
        passage_embeddings = (
            self._load_passage_embeddings(callback) if not snapshot.terminal else ()
        )
        resolution = PdfPostprocessResolution(
            doi=metadata_resolution.doi,
            journal=metadata_resolution.journal,
            publisher=metadata_resolution.publisher,
            publish_date=metadata_resolution.publish_date,
            field_provenance=metadata_resolution.field_provenance,
            embedding=callback.embedding,
            embedding_model_revision=callback.embedding_model_revision,
            embedding_source_digest=callback.embedding_source_digest,
            passage_embeddings=passage_embeddings,
            passage_embedding_model_revision=(
                callback.passage_embedding_artifact.model_revision
                if passage_embeddings
                and callback.passage_embedding_artifact is not None
                else None
            ),
        )
        finalize_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        result = await self._executor.command_async(
            lambda capabilities: capabilities.job_callbacks.complete_pdf_postprocess(
                actor=actor,
                operation=finalize_operation,
                job_id=job_id,
                payload=payload,
                resolution=resolution,
            )
        )
        if callback.passage_embedding_artifact is not None:
            if not s3_service.delete_file(
                callback.passage_embedding_artifact.storage_key
            ):
                logger.warning(
                    "paper.pdf_postprocess.passage_artifact_cleanup_failed",
                    extra={"job_id": str(job_id)},
                )
        return result

    @staticmethod
    def _load_passage_embeddings(
        callback: PdfPostprocessCallback,
    ) -> tuple[PassageEmbeddingRecord, ...]:
        metadata = callback.passage_embedding_artifact
        if metadata is None:
            return ()
        expected_key = (
            f"jobs/pdf-postprocess/{callback.task_id}/passage-embeddings-v1.bin"
        )
        try:
            if metadata.storage_key != expected_key:
                raise ValueError("passage embedding artifact key does not match job")
            if metadata.model_revision != EMBEDDING_MODEL_REVISION:
                raise ValueError("passage embedding model revision is unsupported")
            if s3_service.object_size_bytes(metadata.storage_key) != metadata.byte_size:
                raise ValueError("passage embedding artifact size changed")
            data = s3_service.download_bytes(metadata.storage_key)
            if len(data) != metadata.byte_size:
                raise ValueError("passage embedding artifact size changed")
            if hashlib.sha256(data).hexdigest() != metadata.sha256:
                raise ValueError("passage embedding artifact digest mismatch")
            artifact = decode_passage_embedding_artifact(data)
            if (
                artifact.model_revision != metadata.model_revision
                or artifact.dimension != metadata.dimension
                or len(artifact.records) != metadata.passage_count
            ):
                raise ValueError("passage embedding artifact metadata mismatch")
            return artifact.records
        except Exception:
            logger.exception(
                "paper.pdf_postprocess.passage_artifact_rejected",
                extra={"job_id": str(callback.task_id)},
            )
            return ()

    def _resolve_external(
        self,
        actor: Actor,
        operation: OperationContext,
        fields: CitationFields,
    ) -> PdfPostprocessResolution:
        deterministic_patch = CitationMetadataPatch()
        identity_mismatch = False
        try:
            deterministic = self._provider.deterministic(
                actor=actor,
                operation=operation,
                fields=fields,
            )
            deterministic_patch = deterministic.patch
            identity_mismatch = deterministic.identity_mismatch
        except Exception:
            logger.exception("paper.pdf_metadata.deterministic_resolution_failed")

        resolved_fields = _apply_patch(fields, deterministic_patch)
        agentic_patch = CitationMetadataPatch()
        missing_fields = bibliographic_gaps(resolved_fields)
        if missing_fields and not identity_mismatch:
            try:
                agentic = self._provider.agentic(
                    actor=actor,
                    fields=resolved_fields,
                    missing_fields=missing_fields,
                    steps=[],
                    filled_by="pdf_postprocess",
                )
                agentic_patch = agentic.patch
            except Exception:
                logger.exception("paper.pdf_metadata.agentic_resolution_failed")

        return PdfPostprocessResolution(
            doi=agentic_patch.doi or deterministic_patch.doi,
            journal=agentic_patch.journal or deterministic_patch.journal,
            publisher=(agentic_patch.publisher or deterministic_patch.publisher),
            publish_date=(
                agentic_patch.publish_date or deterministic_patch.publish_date
            ),
            field_provenance=agentic_patch.field_provenance,
        )


def _require_fields(snapshot: PdfPostprocessSnapshot) -> CitationFields:
    if snapshot.fields is None:
        raise RuntimeError("pdf_postprocess_snapshot_fields_missing")
    return snapshot.fields


def _apply_patch(
    fields: CitationFields,
    patch: CitationMetadataPatch,
) -> CitationFields:
    return CitationFields(
        title=fields.title,
        authors=list(fields.authors),
        publish_date=fields.publish_date or patch.publish_date,
        journal=fields.journal or patch.journal,
        publisher=fields.publisher or patch.publisher,
        doi=fields.doi or patch.doi,
    )


__all__ = [
    "PdfPostprocessReader",
    "PdfPostprocessSnapshot",
    "PdfPostprocessWorkflow",
]
