from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.bootstrap.adapters.job_completion_processor import _execute_post_commit
from app.helpers.s3 import S3Service
from app.modules.jobs.application.callbacks import (
    ReleaseJobConcurrency,
    DeleteJobResultArtifacts,
)
from app.modules.jobs.infrastructure.result_effects import decode_effect, encode_effect


def test_versioned_effect_preserves_uuid_and_rejects_unknown_version():
    action = ReleaseJobConcurrency(user_id=7, category="background", job_id=uuid4())
    payload = encode_effect(action)
    assert decode_effect(payload) == action
    with pytest.raises(ValueError, match="version_unsupported"):
        decode_effect({**payload, "version": 2})
    assert (
        decode_effect(encode_effect(DeleteJobResultArtifacts(uuid4()))).__class__
        is DeleteJobResultArtifacts
    )


@pytest.mark.asyncio
async def test_durable_release_retries_redis_errors_instead_of_acknowledging():
    redis = MagicMock()
    redis.zrem = AsyncMock(side_effect=RedisError("temporarily unavailable"))
    action = ReleaseJobConcurrency(user_id=7, category="background", job_id=uuid4())
    with patch("app.helpers.ai_limits._redis_client", return_value=redis):
        with pytest.raises(RedisError):
            await _execute_post_commit(action, strict=True)
        await _execute_post_commit(action)
    assert redis.zrem.await_count == 2


@pytest.mark.asyncio
async def test_artifact_cleanup_awaits_only_derived_job_namespaces():
    job_id = uuid4()
    service = MagicMock(spec=S3Service)
    transfer = service._transfers.return_value
    transfer.delete_prefix_pages = AsyncMock(return_value=False)
    assert not await S3Service.delete_job_result_artifacts(service, job_id)
    transfer.delete_prefix_pages.assert_awaited_once_with(
        (f"jobs/results/{job_id}/", f"jobs/checkpoints/{job_id}/")
    )


@pytest.mark.asyncio
async def test_cleanup_cancellation_closes_operation_before_another_effect():
    import asyncio

    entered, closed = asyncio.Event(), asyncio.Event()

    async def cleanup(_job_id):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    with patch("app.helpers.s3.s3_service.delete_job_result_artifacts", cleanup):
        task = asyncio.create_task(
            _execute_post_commit(DeleteJobResultArtifacts(uuid4()), strict=True)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
