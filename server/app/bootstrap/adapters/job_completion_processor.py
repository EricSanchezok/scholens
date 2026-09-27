"""Resume authenticated Job causality and own post-commit callback effects."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from contextlib import nullcontext
from typing import TYPE_CHECKING
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.pdf_postprocess import PdfPostprocessWorkflow
from app.bootstrap.workflows.zotero import ZoteroBackgroundWorkflow
from app.bootstrap.adapters.document_bibliography import (
    DocumentBibliographyResolution,
    bibliography_snapshot,
)
from app.database.product_analytics import track_event
from app.helpers.ai_limits import release_concurrency_by_id
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
    JobSourceUrlResponse,
    SourceReadyCallback,
)
from app.modules.papers.application.ingestion import SourceReadyResult
from app.modules.papers.domain.citations import CitationFields
from app.modules.jobs.application.callbacks import (
    JobCompletionResult,
    JobPostCommitAction,
    DeleteJobResultArtifacts,
    RecordJobTelemetry,
    ReleaseJobConcurrency,
    SettleJobUsage,
)
from app.modules.jobs.application.causality import (
    JobCausalityFacts,
    require_job_causality_owner,
)
from app.modules.jobs.infrastructure.causality import (
    SqlAlchemyJobCausalityResolver,
)
from app.modules.jobs.infrastructure.research_callbacks import settle_jobs_usage
from app.modules.jobs.application.results import ReservedJobResult
from app.llm.token_credits import llm_usage_context
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    JobOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.bootstrap.workflows.paper_ingestion import PaperSourceResolver


@dataclass(frozen=True, slots=True)
class _ResumedJob:
    actor: Actor | None
    operation: OperationContext


def _lease_categories_for_operation(operation: JobOperation) -> tuple[str, ...]:
    """Map a job operation to the Redis concurrency categories it holds.

    Callback-contract failures are durably marked failed before these categories
    are released. PDF_POSTPROCESS and Zotero jobs do not hold Redis leases
    (Zotero uses a DB claim) and map to no categories.
    """
    return {
        JobOperation.PDF_PROCESS: ("background",),
        JobOperation.AUDIO_GENERATE: ("background", "audio"),
        JobOperation.DATA_TABLE_GENERATE: ("background",),
    }.get(operation, ())


class JobCompletionProcessor:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        executor: ApplicationExecutor[ApplicationCapabilities],
        operation_factory: OperationContextFactory,
        pdf_postprocess: PdfPostprocessWorkflow,
        zotero_background: ZoteroBackgroundWorkflow,
        source_resolver: PaperSourceResolver,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._operation_factory = operation_factory
        self._pdf_postprocess = pdf_postprocess
        self._zotero_background = zotero_background
        self._source_resolver = source_resolver

    def apply_inbox(
        self, reservation: ReservedJobResult, payload: dict[str, object]
    ) -> JobCompletionResult:
        """Called by the bounded consumer thread; application is one transaction."""
        facts = self._causality(job_id=reservation.job_id)
        resumed = self._resume(
            facts=facts,
            verified=VerifiedJobCallback(
                request_id=reservation.request_id,
                delivery_ref=reservation.delivery_ref,
            ),
            allow_unavailable_owner=True,
        )
        context = (
            llm_usage_context(
                user_id=resumed.actor.id,
                feature=facts.operation.value,
                operation_id=str(reservation.job_id),
            )
            if resumed.actor is not None
            else nullcontext()
        )
        with context:
            return self._executor.command(
                lambda capabilities: capabilities.job_results.apply(
                    reservation=reservation,
                    actor=resumed.actor,
                    operation=resumed.operation,
                    payload=payload,
                )
            )

    async def finish_inbox(self, result: JobCompletionResult) -> None:
        # Async clients remain on the Server event loop that owns their lifetime.
        await self._run_post_commit(result)

    async def execute_effect(self, action: JobPostCommitAction) -> None:
        await _execute_post_commit(action, strict=True)

    def retry_inbox(
        self, reservation: ReservedJobResult, *, error_code: str
    ) -> JobCompletionResult:
        facts = self._causality(job_id=reservation.job_id)
        resumed = self._resume(
            facts=facts,
            verified=VerifiedJobCallback(
                request_id=reservation.request_id, delivery_ref=reservation.delivery_ref
            ),
            allow_unavailable_owner=True,
        )
        return self._executor.command(
            lambda capabilities: capabilities.job_results.retry(
                reservation=reservation,
                actor=resumed.actor,
                operation=resumed.operation,
                error_code=error_code,
            )
        )

    async def resolve_source_url(
        self,
        *,
        job_id: UUID,
        verified: VerifiedJobCallback,
        generation: int | None = None,
    ) -> JobSourceUrlResponse:
        """Resolve a provider-backed source only after its durable job is running."""

        await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.job_results.require_transport(
                job_id=job_id, generation=generation
            ),
        )
        facts = await asyncio.to_thread(self._causality, job_id=job_id)
        resumed = await asyncio.to_thread(self._resume, facts=facts, verified=verified)
        if facts.operation is not JobOperation.PDF_PROCESS:
            raise AppError(
                code="job_operation_mismatch",
                message="Job operation does not match source resolution",
                kind=FailureKind.CONFLICT,
            )
        if resumed.actor is None:
            raise RuntimeError("source_resolution_job_owner_missing")
        actor = resumed.actor
        source = await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.paper_ingestion.source_for_resolution(
                actor=actor,
                job_id=job_id,
            ),
        )
        resolved_url = await self._source_resolver.resolve(
            actor=actor,
            operation=resumed.operation,
            kind=source.kind,
            value=source.value,
        )
        await asyncio.to_thread(
            self._executor.query,
            lambda capabilities: capabilities.job_results.require_transport(
                job_id=job_id, generation=generation
            ),
        )
        return JobSourceUrlResponse(resolved_url=resolved_url)

    async def resolve_bibliography(
        self,
        *,
        job_id: UUID,
        generation: int,
        verified: VerifiedJobCallback,
    ) -> DocumentBibliographyResolution:
        async def require_generation() -> None:
            await asyncio.to_thread(
                self._executor.query,
                lambda capabilities: capabilities.job_results.require_transport(
                    job_id=job_id, generation=generation
                ),
            )

        await require_generation()
        facts = await asyncio.to_thread(self._causality, job_id=job_id)
        resumed = await asyncio.to_thread(self._resume, facts=facts, verified=verified)
        if resumed.actor is None:
            raise AppError(
                code="job_owner_missing",
                message="Job owner is unavailable",
                kind=FailureKind.CONFLICT,
            )
        actor = resumed.actor

        def snapshot() -> tuple[DocumentBibliographyResolution, CitationFields | None]:
            with self._session_factory() as db:
                return bibliography_snapshot(db, job_id=job_id, actor=actor)

        result, fields = await asyncio.to_thread(snapshot)
        if fields is not None:
            try:
                patch = await self._pdf_postprocess.deterministic_bibliography(
                    actor=actor, operation=resumed.operation, fields=fields
                )
            except Exception as exc:
                raise AppError(
                    code="document_bibliography_unavailable",
                    message="Bibliography provider is temporarily unavailable",
                    kind=FailureKind.DEPENDENCY_FAILURE,
                ) from exc
            result = result.model_copy(update={"patch": patch})
        await require_generation()
        return result

    async def complete(
        self,
        *,
        job_id: UUID,
        payload: dict[str, object],
        verified: VerifiedJobCallback,
    ) -> object:
        await asyncio.to_thread(
            self._executor.command,
            lambda capabilities: capabilities.job_results.require_transport(
                job_id=job_id
            ),
        )
        facts = await asyncio.to_thread(self._causality, job_id=job_id)
        resumed = await asyncio.to_thread(self._resume, facts=facts, verified=verified)
        context = (
            llm_usage_context(
                user_id=resumed.actor.id,
                feature=facts.operation.value,
                operation_id=str(job_id),
            )
            if resumed.actor is not None
            else nullcontext()
        )
        with context:
            return await self._complete_resumed(
                job_id=job_id, payload=payload, facts=facts, resumed=resumed
            )

    async def _complete_resumed(
        self,
        *,
        job_id: UUID,
        payload: dict[str, object],
        facts: JobCausalityFacts,
        resumed: _ResumedJob,
    ) -> object:
        job_operation = facts.operation
        try:
            if job_operation is JobOperation.PDF_POSTPROCESS:
                if resumed.actor is None:
                    raise RuntimeError("pdf_postprocess_job_owner_missing")
                result = await self._pdf_postprocess.complete(
                    actor=resumed.actor,
                    operation=resumed.operation,
                    job_id=job_id,
                    payload=payload,
                )
                await self._run_post_commit(result)
                return result.value
            if job_operation in {
                JobOperation.ZOTERO_IMPORT,
                JobOperation.ZOTERO_SYNC,
            }:
                if resumed.actor is None:
                    raise RuntimeError("zotero_job_owner_missing")
                return await self._zotero_background.complete(
                    actor=resumed.actor,
                    operation=resumed.operation,
                    job_id=job_id,
                    payload=payload,
                )
            result = await asyncio.to_thread(
                self._executor.command,
                lambda capabilities: capabilities.job_callbacks.complete(
                    actor=resumed.actor,
                    operation=resumed.operation,
                    job_id=job_id,
                    payload=payload,
                ),
            )
            await self._run_post_commit(result)
            return result.value
        except AppError as exc:
            if exc.code != "job_callback_invalid":
                raise
            failed = await asyncio.to_thread(
                self._executor.command,
                lambda capabilities: capabilities.job_callbacks.fail(
                    actor=resumed.actor,
                    operation=resumed.operation,
                    job_id=job_id,
                    callback=JobFailureCallback(
                        task_id=job_id,
                        error_code="job_callback_invalid",
                    ),
                ),
            )
            if failed.claimed:
                await self._release_terminal_failure_leases(facts=facts)
            return failed

    def source_ready(
        self,
        *,
        job_id: UUID,
        callback: SourceReadyCallback,
        verified: VerifiedJobCallback,
    ) -> object:
        """Apply metadata-only source materialization before PDF parsing."""
        if callback.task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Job callback ID does not match",
                kind=FailureKind.CONFLICT,
            )
        facts = self._causality(job_id=job_id)
        resumed = self._resume(facts=facts, verified=verified)
        if facts.operation is not JobOperation.PDF_PROCESS:
            raise AppError(
                code="job_operation_mismatch",
                message="Job operation does not match source callback",
                kind=FailureKind.CONFLICT,
            )
        if resumed.actor is None:
            raise RuntimeError("source_ready_job_owner_missing")
        actor = resumed.actor

        def apply_source(capabilities: ApplicationCapabilities) -> SourceReadyResult:
            capabilities.job_results.require_transport(
                job_id=job_id, generation=callback.claim_generation
            )
            return capabilities.paper_ingestion.source_ready(
                actor=actor,
                operation=resumed.operation,
                job_id=job_id,
                source_sha256=callback.source_sha256,
                size_bytes=callback.size_bytes,
                staging_object_key=callback.staging_object_key,
                filename=callback.filename,
                attempt=callback.attempt,
            )

        result = self._executor.command(apply_source)
        return asdict(result)

    async def _release_terminal_failure_leases(
        self,
        *,
        facts: JobCausalityFacts,
    ) -> None:
        """Release Redis leases after an invalid callback is durably failed.

        Callback contract validation happens before operation-specific handlers
        can produce their normal ``ReleaseJobConcurrency`` post-commit actions.
        Mark the job failed in a separate committed operation first, then release
        only that terminal job's leases. Unexpected handler and database errors
        retain their leases until retry or TTL instead of weakening concurrency
        protection for work that may still be active.
        """
        requested_by_id = facts.requested_by_id
        if requested_by_id is None:
            return
        for category in _lease_categories_for_operation(facts.operation):
            try:
                await release_concurrency_by_id(
                    user_id=requested_by_id,
                    category=category,
                    operation_id=str(facts.job_id),
                )
            except Exception:
                logger.exception(
                    "jobs.completion.lease_compensation_failed",
                    extra={
                        "job_id": str(facts.job_id),
                        "category": category,
                    },
                )

    def fail(
        self,
        *,
        job_id: UUID,
        callback: JobFailureCallback,
        verified: VerifiedJobCallback,
    ) -> JobClaimResponse:
        self._executor.command(
            lambda capabilities: capabilities.job_results.require_transport(
                job_id=job_id
            )
        )
        facts = self._causality(job_id=job_id)
        resumed = self._resume(facts=facts, verified=verified)
        return self._executor.command(
            lambda capabilities: capabilities.job_callbacks.fail(
                actor=resumed.actor,
                operation=resumed.operation,
                job_id=job_id,
                callback=callback,
            )
        )

    def _resume(
        self,
        *,
        facts: JobCausalityFacts,
        verified: VerifiedJobCallback,
        allow_unavailable_owner: bool = False,
    ) -> _ResumedJob:
        requested_by_id = facts.requested_by_id
        try:
            actor = (
                self._executor.query(
                    lambda capabilities: capabilities.identity.resolve_actor_by_user_id(
                        requested_by_id
                    )
                )
                if requested_by_id is not None
                else None
            )
        except AppError as exc:
            if not allow_unavailable_owner or exc.code != "identity_profile_incomplete":
                raise
            actor = None
        if actor is not None or not allow_unavailable_owner:
            require_job_causality_owner(facts=facts, actor=actor)
        operation = self._operation_factory.resume(
            correlation_id=facts.correlation_id,
            causation_id=facts.origin_operation_id,
            initiated_by=OperationInitiator.SYSTEM,
            origin=JobOrigin(
                job_id=facts.job_id,
                delivery_ref=verified.delivery_ref,
                request_id=verified.request_id,
            ),
            credential=CredentialRef(CredentialKind.INTERNAL_SIGNATURE),
        )
        return _ResumedJob(actor=actor, operation=operation)

    def _causality(self, *, job_id: UUID) -> JobCausalityFacts:
        with self._session_factory() as session:
            return SqlAlchemyJobCausalityResolver(session).resolve(job_id=job_id)

    async def _run_post_commit(self, result: JobCompletionResult) -> None:
        for action in result.post_commit:
            await _execute_post_commit(action)


async def _execute_post_commit(
    action: JobPostCommitAction, *, strict: bool = False
) -> None:
    try:
        if isinstance(action, DeleteJobResultArtifacts):
            from app.helpers.s3 import s3_service

            if not await s3_service.delete_job_result_artifacts(action.job_id):
                raise RuntimeError("job_artifact_cleanup_incomplete")
            return
        if isinstance(action, ReleaseJobConcurrency):
            await release_concurrency_by_id(
                user_id=action.user_id,
                category=action.category,
                operation_id=str(action.job_id),
                raise_on_error=strict,
            )
            return
        if isinstance(action, SettleJobUsage):
            await asyncio.to_thread(
                settle_jobs_usage,
                action.user_id,
                list(action.events),
            )
            return
        if isinstance(action, RecordJobTelemetry):
            track_event(
                action.event,
                properties=dict(action.properties),
                user_id=str(action.actor_id),
            )
            return
        raise TypeError(f"unsupported Job post-commit action: {type(action).__name__}")
    except Exception:
        if strict:
            raise
        logger.exception(
            "jobs.post_commit_action.failed",
            extra={"action_type": type(action).__name__},
        )


__all__ = ["JobCompletionProcessor"]
