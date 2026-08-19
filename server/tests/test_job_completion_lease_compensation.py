"""Lease compensation safety net for job completion processors.

When a completion handler raises, the normal ``ReleaseJobConcurrency``
post-commit never runs. The processor must still release the Redis
concurrency categories the operation acquired so a failed job does not
occupy a slot until the TTL expires.
"""

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
from app.shared.domain.enums import JobOperation


def _facts(operation: JobOperation, user_id: int | None = 7) -> JobCausalityFacts:
    return JobCausalityFacts(
        job_id=uuid4(),
        operation=operation,
        requested_by_id=user_id,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )


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
async def test_complete_releases_leases_when_handler_raises() -> None:
    job_id = uuid4()
    facts = _facts(JobOperation.AUDIO_GENERATE)
    # job_id inside facts must match the dispatched job_id
    facts = JobCausalityFacts(
        job_id=job_id,
        operation=JobOperation.AUDIO_GENERATE,
        requested_by_id=7,
        correlation_id=facts.correlation_id,
        origin_operation_id=facts.origin_operation_id,
    )
    release = AsyncMock()
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=MagicMock(),
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
    )
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=MagicMock(), operation=MagicMock())
    )
    processor._executor.command_async = AsyncMock(  # type: ignore[assignment]
        side_effect=RuntimeError("boom")
    )

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await processor.complete(
                job_id=job_id,
                payload={},
                verified=MagicMock(),
            )

    assert release.await_count == 2
    release.assert_any_await(
        user_id=7,
        category="background",
        operation_id=str(job_id),
    )
    release.assert_any_await(
        user_id=7,
        category="audio",
        operation_id=str(job_id),
    )


@pytest.mark.asyncio
async def test_complete_releases_background_when_pdf_process_handler_raises() -> None:
    job_id = uuid4()
    facts = JobCausalityFacts(
        job_id=job_id,
        operation=JobOperation.PDF_PROCESS,
        requested_by_id=7,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )
    release = AsyncMock()
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=MagicMock(),
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
    )
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=MagicMock(), operation=MagicMock())
    )
    processor._executor.command_async = AsyncMock(  # type: ignore[assignment]
        side_effect=RuntimeError("boom")
    )

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await processor.complete(
                job_id=job_id,
                payload={},
                verified=MagicMock(),
            )

    release.assert_awaited_once_with(
        user_id=7,
        category="background",
        operation_id=str(job_id),
    )


@pytest.mark.asyncio
async def test_complete_does_not_release_when_owner_missing() -> None:
    job_id = uuid4()
    facts = JobCausalityFacts(
        job_id=job_id,
        operation=JobOperation.PDF_PROCESS,
        requested_by_id=None,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )
    release = AsyncMock()
    processor = JobCompletionProcessor(
        session_factory=MagicMock(),
        executor=MagicMock(),
        operation_factory=MagicMock(),
        pdf_postprocess=MagicMock(),
        zotero_background=MagicMock(),
    )
    processor._causality = MagicMock(return_value=facts)  # type: ignore[method-assign]
    processor._resume = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(actor=MagicMock(), operation=MagicMock())
    )
    processor._executor.command_async = AsyncMock(  # type: ignore[assignment]
        side_effect=RuntimeError("boom")
    )

    with patch(
        "app.bootstrap.adapters.job_completion_processor.release_concurrency_by_id",
        release,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await processor.complete(
                job_id=job_id,
                payload={},
                verified=MagicMock(),
            )

    release.assert_not_awaited()
