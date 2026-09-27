"""Terminal lease handling for invalid authenticated job callbacks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.job_completion_processor import (
    JobCompletionProcessor,
    _lease_categories_for_operation,
)
from app.modules.jobs.application.causality import JobCausalityFacts
from app.modules.jobs.application.contracts import JobClaimResponse
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation


def _facts(operation: JobOperation, user_id: int | None = 7) -> JobCausalityFacts:
    return JobCausalityFacts(
        job_id=uuid4(),
        operation=operation,
        requested_by_id=user_id,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )


def _processor(
    *,
    facts: JobCausalityFacts,
    completion_error: Exception,
    failure_claimed: bool = True,
) -> tuple[JobCompletionProcessor, MagicMock]:
    callbacks = MagicMock()
    callbacks.complete.side_effect = completion_error
    callbacks.fail.return_value = JobClaimResponse(claimed=failure_claimed)
    executor = MagicMock()
    executor.command_async = AsyncMock(side_effect=completion_error)
    executor.command.side_effect = lambda operation: operation(
        SimpleNamespace(job_callbacks=callbacks, job_results=MagicMock())
    )
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=executor,
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
        source_resolver=MagicMock(),
    )
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=MagicMock(), operation=MagicMock())
    )
    return processor, callbacks


@pytest.mark.asyncio
async def test_completion_transaction_does_not_block_the_request_event_loop() -> None:
    import threading
    from app.modules.jobs.application.callbacks import JobCompletionResult

    request_thread = threading.get_ident()
    facts = _facts(JobOperation.PDF_PROCESS)
    processor, callbacks = _processor(
        facts=facts, completion_error=AssertionError("Must use a worker transaction")
    )

    def complete(**_kwargs):
        assert threading.get_ident() != request_thread
        return JobCompletionResult(value={"accepted": True})

    callbacks.complete.side_effect = complete
    result = await processor.complete(
        job_id=facts.job_id, payload={}, verified=MagicMock()
    )
    assert result == {"accepted": True}


def test_lease_categories_for_operation() -> None:
    assert _lease_categories_for_operation(JobOperation.PDF_PROCESS) == ("background",)
    assert _lease_categories_for_operation(JobOperation.AUDIO_GENERATE) == (
        "background",
        "audio",
    )
    assert _lease_categories_for_operation(JobOperation.DATA_TABLE_GENERATE) == (
        "background",
    )
    assert _lease_categories_for_operation(JobOperation.PDF_POSTPROCESS) == ()
    assert _lease_categories_for_operation(JobOperation.ZOTERO_IMPORT) == ()
    assert _lease_categories_for_operation(JobOperation.ZOTERO_SYNC) == ()
    assert _lease_categories_for_operation(JobOperation.DOCUMENT_GC) == ()
    assert _lease_categories_for_operation(JobOperation.STORAGE_DELETE) == ()
    assert _lease_categories_for_operation(JobOperation.DOCUMENT_REFLOW) == ()


@pytest.mark.asyncio
async def test_source_url_resolution_resumes_the_owned_durable_job() -> None:
    facts = _facts(JobOperation.PDF_PROCESS)
    source_port = MagicMock()
    source_port.source_for_resolution.return_value = SimpleNamespace(
        kind="doi", value="10.1000/example"
    )
    executor = MagicMock()
    fences = MagicMock()
    executor.query.side_effect = lambda operation: operation(
        SimpleNamespace(paper_ingestion=source_port, job_results=fences)
    )
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value="https://repository.example/paper.pdf")
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=executor,
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
        source_resolver=resolver,
    )
    actor = MagicMock()
    operation = MagicMock()
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=actor, operation=operation)
    )

    result = await processor.resolve_source_url(
        job_id=facts.job_id,
        verified=MagicMock(),
    )

    assert fences.require_transport.call_count == 2
    fences.require_transport.assert_called_with(job_id=facts.job_id, generation=None)
    assert result.resolved_url == "https://repository.example/paper.pdf"
    source_port.source_for_resolution.assert_called_once_with(
        actor=actor,
        job_id=facts.job_id,
    )
    resolver.resolve.assert_awaited_once_with(
        actor=actor,
        operation=operation,
        kind="doi",
        value="10.1000/example",
    )


@pytest.mark.asyncio
async def test_invalid_callback_is_failed_before_audio_leases_are_released() -> None:
    facts = _facts(JobOperation.AUDIO_GENERATE)
    processor, callbacks = _processor(
        facts=facts,
        completion_error=AppError(
            code="job_callback_invalid",
            message="Job callback payload is invalid for its operation",
            kind=FailureKind.UNPROCESSABLE,
        ),
    )
    release = AsyncMock()

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        result = await processor.complete(
            job_id=facts.job_id,
            payload={},
            verified=MagicMock(),
        )

    assert result.claimed is True
    failure = callbacks.fail.call_args.kwargs["callback"]
    assert failure.task_id == facts.job_id
    assert failure.error_code == "job_callback_invalid"
    assert release.await_count == 2
    release.assert_any_await(
        user_id=7,
        category="background",
        operation_id=str(facts.job_id),
    )
    release.assert_any_await(
        user_id=7,
        category="audio",
        operation_id=str(facts.job_id),
    )


@pytest.mark.asyncio
async def test_invalid_pdf_callback_releases_background_after_terminal_failure() -> (
    None
):
    facts = _facts(JobOperation.PDF_PROCESS)
    processor, _callbacks = _processor(
        facts=facts,
        completion_error=AppError(
            code="job_callback_invalid",
            message="Job callback payload is invalid for its operation",
            kind=FailureKind.UNPROCESSABLE,
        ),
    )
    release = AsyncMock()

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        result = await processor.complete(
            job_id=facts.job_id,
            payload={},
            verified=MagicMock(),
        )

    assert result.claimed is True
    release.assert_awaited_once_with(
        user_id=7,
        category="background",
        operation_id=str(facts.job_id),
    )


@pytest.mark.asyncio
async def test_unexpected_handler_error_does_not_weaken_active_lease() -> None:
    facts = _facts(JobOperation.AUDIO_GENERATE)
    processor, callbacks = _processor(
        facts=facts,
        completion_error=RuntimeError("database unavailable"),
    )
    release = AsyncMock()

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await processor.complete(
                job_id=facts.job_id,
                payload={},
                verified=MagicMock(),
            )

    callbacks.fail.assert_not_called()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_unclaimed_invalid_callback_does_not_release_lease() -> None:
    facts = _facts(JobOperation.PDF_PROCESS)
    processor, _callbacks = _processor(
        facts=facts,
        completion_error=AppError(
            code="job_callback_invalid",
            message="Job callback payload is invalid for its operation",
            kind=FailureKind.UNPROCESSABLE,
        ),
        failure_claimed=False,
    )
    release = AsyncMock()

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        result = await processor.complete(
            job_id=facts.job_id,
            payload={},
            verified=MagicMock(),
        )

    assert result.claimed is False
    release.assert_not_awaited()


@pytest.mark.parametrize("lose_fence", [False, True])
@pytest.mark.asyncio
async def test_bibliography_has_no_open_transaction_during_provider_and_rechecks_fence(
    lose_fence,
):
    import threading
    from app.bootstrap.adapters.document_bibliography import (
        DocumentBibliographyResolution,
    )
    from app.modules.papers.domain.citations import CitationFields
    from app.modules.papers.application.citations import CitationMetadataPatch
    from app.bootstrap.adapters import job_completion_processor as module

    facts = _facts(JobOperation.DOCUMENT_BIBLIOGRAPHY)
    processor, _ = _processor(facts=facts, completion_error=AssertionError())
    fences = MagicMock()
    processor._executor.query.side_effect = lambda fn: fn(
        SimpleNamespace(job_results=fences)
    )
    closed = []
    processor._session_factory.return_value.__exit__.side_effect = lambda *args: (
        closed.append(True)
    )
    thread_id = threading.get_ident()
    snapshot = DocumentBibliographyResolution(
        content_digest="a" * 64, identity_digest="b" * 64
    )

    def read(*args, **kwargs):
        assert threading.get_ident() != thread_id
        return snapshot, CitationFields(title="Title", authors=["Ada"])

    async def resolve(**kwargs):
        assert threading.get_ident() == thread_id
        assert closed == [True]
        if lose_fence:
            fences.require_transport.side_effect = AppError(
                code="job_execution_fence_rejected",
                message="Lost",
                kind=FailureKind.CONFLICT,
            )
        return CitationMetadataPatch(doi="10.1000/test")

    processor._pdf_postprocess.deterministic_bibliography = AsyncMock(
        side_effect=resolve
    )
    with patch.object(module, "bibliography_snapshot", side_effect=read):
        if lose_fence:
            with pytest.raises(AppError, match="job_execution_fence_rejected"):
                await processor.resolve_bibliography(
                    job_id=facts.job_id, generation=3, verified=MagicMock()
                )
        else:
            result = await processor.resolve_bibliography(
                job_id=facts.job_id, generation=3, verified=MagicMock()
            )
            assert result.patch.doi == "10.1000/test"
    assert fences.require_transport.call_count == 2
    fences.require_transport.assert_called_with(job_id=facts.job_id, generation=3)
