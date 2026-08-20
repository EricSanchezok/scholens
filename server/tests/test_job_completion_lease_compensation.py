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
    callbacks.fail.return_value = JobClaimResponse(claimed=failure_claimed)
    executor = MagicMock()
    executor.command_async = AsyncMock(side_effect=completion_error)
    executor.command.side_effect = lambda operation: operation(
        SimpleNamespace(job_callbacks=callbacks)
    )
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=executor,
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
    )
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=MagicMock(), operation=MagicMock())
    )
    return processor, callbacks


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
