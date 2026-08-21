"""Short-transaction, cache-aside streaming translation workflow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from app.bootstrap.capabilities import ApplicationCapabilities
from app.llm.token_credits import llm_usage_context
from app.modules.translations.application import (
    PreparedTranslation,
    TranslationCapacity,
    TranslationCapacityLease,
    TranslationRequest,
    TranslationResultIdentity,
    TranslationResultStore,
    TranslationResultValue,
    TranslationSingleFlight,
    TranslationStreamEvent,
    TranslationStreamFailure,
    TranslationStreamFailureKind,
    TranslationStreamProvider,
    TranslationStreamSpec,
)
from app.modules.translations.domain import (
    MAX_TRANSLATED_TEXT_CHARS,
    TranslationFingerprint,
    translation_identity_key,
    translation_instructions_hash,
    translation_paper_title_hash,
    translation_source_hash,
    validate_translated_text,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    ErrorEnvelope,
    OperationContext,
)
from app.shared.domain import AppError, FailureKind
from scholens_observability import (
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    add_counter,
    build_snapshot,
    current_context,
    log_event,
)

logger = logging.getLogger(__name__)

TRANSLATION_RESULT_SCHEMA_REVISION = "translation-result-v1"
SINGLE_FLIGHT_WAIT_ATTEMPTS = 120
SINGLE_FLIGHT_WAIT_SECONDS = 0.25
_STREAM_FAILURE_DETAILS = {
    TranslationStreamFailureKind.PROVIDER_UNAVAILABLE: (
        "translation_provider_unavailable",
        "Translation provider is temporarily unavailable",
    ),
    TranslationStreamFailureKind.USAGE_SETTLEMENT_FAILED: (
        "translation_usage_settlement_failed",
        "Translation completed but usage recording failed",
    ),
    TranslationStreamFailureKind.INTERRUPTED: (
        "translation_stream_interrupted",
        "Translation stream was interrupted",
    ),
}


class TranslationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        result_store: TranslationResultStore,
        singleflight: TranslationSingleFlight,
        provider: TranslationStreamProvider,
        capacity: TranslationCapacity,
        diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
    ) -> None:
        self._executor = executor
        self._result_store = result_store
        self._singleflight = singleflight
        self._provider = provider
        self._capacity = capacity
        self._diagnostic_recorder = (
            diagnostic_recorder or NullDiagnosticSnapshotRecorder()
        )

    async def open_stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: TranslationRequest,
        client_ip: str,
    ) -> AsyncIterator[TranslationStreamEvent]:
        prepared = self._executor.query(
            lambda capabilities: _prepare_translation(
                capabilities=capabilities,
                actor=actor,
                document_id=document_id,
                request=request,
            )
        )
        return await self._open_prepared(
            actor=actor,
            operation=operation,
            prepared=prepared,
            client_ip=client_ip,
        )

    async def open_reflow_block_stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        block_id: str,
        client_ip: str,
    ) -> AsyncIterator[TranslationStreamEvent]:
        prepared = self._executor.query(
            lambda capabilities: _prepare_reflow_block_translation(
                capabilities=capabilities,
                actor=actor,
                document_id=document_id,
                block_id=block_id,
            )
        )
        return await self._open_prepared(
            actor=actor,
            operation=operation,
            prepared=prepared,
            client_ip=client_ip,
        )

    async def _open_prepared(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedTranslation,
        client_ip: str,
    ) -> AsyncIterator[TranslationStreamEvent]:
        fingerprint = TranslationFingerprint(
            schema_revision=TRANSLATION_RESULT_SCHEMA_REVISION,
            prompt_revision=self._provider.prompt_revision(),
            model_revision=self._provider.model_revision(),
            context_kind=prepared.context_kind,
            block_id=prepared.block_id,
            document_id=prepared.document_id,
            paper_title_hash=translation_paper_title_hash(prepared.paper_title),
            source_text=prepared.source_text,
            source_language=prepared.source_language,
            target_language=prepared.target_language,
            custom_instructions_hash=translation_instructions_hash(
                prepared.custom_instructions
            ),
        )
        identity_key = translation_identity_key(fingerprint)
        result_identity = TranslationResultIdentity(
            key=identity_key,
            context_kind=prepared.context_kind,
            document_id=prepared.document_id,
            block_id=prepared.block_id,
            target_language=prepared.target_language,
            source_hash=translation_source_hash(prepared.source_text),
            instructions_hash=fingerprint.custom_instructions_hash,
            prompt_revision=fingerprint.prompt_revision,
            profile_revision=fingerprint.model_revision,
        )
        cached = await self._result_store.get(identity_key)
        if cached is not None:
            return _cached_stream(cached)

        lease_token = await self._singleflight.acquire(identity_key)
        if lease_token is None:
            for _ in range(SINGLE_FLIGHT_WAIT_ATTEMPTS):
                await asyncio.sleep(SINGLE_FLIGHT_WAIT_SECONDS)
                cached = await self._result_store.get(identity_key)
                if cached is not None:
                    return _cached_stream(cached)
            raise AppError(
                code="translation_in_progress",
                message="An identical translation is still in progress",
                kind=FailureKind.CONFLICT,
                retryable=True,
            )

        try:
            await self._capacity.enforce_rate(
                user_id=actor.id,
                client_ip=client_ip,
            )
            self._executor.query(
                lambda capabilities: capabilities.translations.require_token_credits(
                    actor=actor
                )
            )
            capacity_lease = await self._capacity.acquire(
                user_id=actor.id,
                operation_id=operation.trace.operation_id,
            )
        except BaseException:
            if lease_token is not None:
                await self._singleflight.release(identity_key, lease_token)
            raise

        return self._provider_stream(
            actor=actor,
            operation=operation,
            prepared=prepared,
            result_identity=result_identity,
            cache_lease_token=lease_token,
            capacity_lease=capacity_lease,
        )

    async def _provider_stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedTranslation,
        result_identity: TranslationResultIdentity,
        cache_lease_token: str | None,
        capacity_lease: TranslationCapacityLease,
    ) -> AsyncIterator[TranslationStreamEvent]:
        chunks: list[str] = []
        translated_chars = 0
        yield TranslationStreamEvent(
            event="start",
            data={
                "target_language": prepared.target_language,
                "cache_hit": False,
            },
        )
        try:
            with llm_usage_context(
                user_id=actor.id,
                feature="translation",
                operation_id=str(operation.trace.operation_id),
            ):
                async for chunk in self._provider.stream(
                    TranslationStreamSpec(
                        paper_title=prepared.paper_title,
                        source_text=prepared.source_text,
                        source_language=prepared.source_language,
                        target_language=prepared.target_language,
                        custom_instructions=prepared.custom_instructions,
                        context_kind=prepared.context_kind,
                    )
                ):
                    chunks.append(chunk)
                    translated_chars += len(chunk)
                    if translated_chars > MAX_TRANSLATED_TEXT_CHARS:
                        raise ValueError("translated_text_too_long")
                    yield TranslationStreamEvent(
                        event="delta",
                        data={"text": chunk},
                    )
            translated_text = validate_translated_text("".join(chunks))
            await self._result_store.set(
                identity=result_identity,
                value=TranslationResultValue(
                    translated_text=translated_text,
                    target_language=prepared.target_language,
                ),
            )
            yield TranslationStreamEvent(
                event="complete",
                data={"cache_hit": False},
            )
        except TranslationStreamFailure as exc:
            code, message = _STREAM_FAILURE_DETAILS[exc.kind]
            error = AppError(
                code=code,
                message=message,
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=exc.kind
                is not TranslationStreamFailureKind.USAGE_SETTLEMENT_FAILED,
            )
            yield self._error_event(
                error,
                operation=operation,
                cause=exc,
                actor=actor,
                prepared=prepared,
            )
        except ValueError as exc:
            error = AppError(
                code="translation_result_invalid",
                message="Translation provider returned an invalid result",
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=False,
            )
            yield self._error_event(
                error,
                operation=operation,
                cause=exc,
                actor=actor,
                prepared=prepared,
            )
        except Exception as exc:
            error = AppError(
                code="translation_stream_interrupted",
                message="Translation stream was interrupted",
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=True,
            )
            yield self._error_event(
                error,
                operation=operation,
                cause=exc,
                actor=actor,
                prepared=prepared,
            )
        finally:
            await self._capacity.release(capacity_lease)
            if cache_lease_token is not None:
                await self._singleflight.release(result_identity.key, cache_lease_token)

    def _error_event(
        self,
        error: AppError,
        *,
        operation: OperationContext,
        cause: BaseException,
        actor: Actor,
        prepared: PreparedTranslation,
    ) -> TranslationStreamEvent:
        context = current_context()
        snapshot_id = uuid4()
        envelope = ErrorEnvelope.from_app_error(
            error,
            stage="translation_stream",
            request_id=context.request_id,
            correlation_id=str(operation.trace.correlation_id),
            diagnostic_id=str(snapshot_id),
        )
        try:
            self._diagnostic_recorder.record(
                build_snapshot(
                    snapshot_id=snapshot_id,
                    service=context.service,
                    environment=context.environment,
                    release=context.release,
                    reason="translation_stream_failed",
                    request_id=context.request_id,
                    operation_id=str(operation.trace.operation_id),
                    correlation_id=str(operation.trace.correlation_id),
                    actor_id=str(actor.id),
                    sections={
                        "failure": {
                            "code": error.code,
                            "kind": error.kind.value,
                            "exception_type": type(cause).__name__,
                        },
                        "translation": {
                            "document_id": str(prepared.document_id),
                            "target_language": prepared.target_language,
                        },
                    },
                )
            )
        except Exception as capture_error:
            log_event(
                logger,
                logging.ERROR,
                "diagnostic.snapshot.capture_failed",
                exc_info=capture_error,
                diagnostic_id=str(snapshot_id),
            )
        add_counter(
            "scholens.translation.stream_errors",
            attributes={"code": error.code},
        )
        log_event(
            logger,
            logging.ERROR,
            "translation.stream.failed",
            exc_info=cause,
            error_code=error.code,
            error_kind=error.kind.value,
            retryable=error.retryable,
            diagnostic_id=envelope.diagnostic_id,
        )
        return TranslationStreamEvent(
            event="error",
            data=envelope.to_dict(),
        )


def _prepare_translation(
    *,
    capabilities: ApplicationCapabilities,
    actor: Actor,
    document_id: UUID,
    request: TranslationRequest,
) -> PreparedTranslation:
    paper = capabilities.paper_details(
        actor=actor,
        document_id=document_id,
    )
    return capabilities.translations.prepare(
        actor=actor,
        document_id=document_id,
        paper_title=paper.title,
        request=request,
    )


def _prepare_reflow_block_translation(
    *,
    capabilities: ApplicationCapabilities,
    actor: Actor,
    document_id: UUID,
    block_id: str,
) -> PreparedTranslation:
    source = capabilities.document_reflows.translation_source(
        actor=actor,
        document_id=document_id,
        block_id=block_id,
    )
    return capabilities.translations.prepare_reflow_block(
        actor=actor,
        document_id=document_id,
        paper_title=source.paper_title,
        block_id=source.block.id,
        source_markdown=source.block.render_markdown,
    )


async def _cached_stream(
    value: TranslationResultValue,
) -> AsyncIterator[TranslationStreamEvent]:
    yield TranslationStreamEvent(
        event="start",
        data={
            "target_language": value.target_language,
            "cache_hit": True,
        },
    )
    yield TranslationStreamEvent(
        event="delta",
        data={"text": value.translated_text},
    )
    yield TranslationStreamEvent(
        event="complete",
        data={"cache_hit": True},
    )
