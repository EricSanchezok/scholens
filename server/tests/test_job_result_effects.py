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


def test_artifact_cleanup_is_bounded_and_accepts_only_job_owned_namespaces():
    job_id = uuid4()
    service = MagicMock(spec=S3Service)
    service.s3_client = MagicMock()
    service._require_bucket.return_value = "fixture"
    service.s3_client.list_objects_v2.side_effect = [
        {
            "Contents": [{"Key": f"jobs/results/{job_id}/1/result.json"}],
            "IsTruncated": True,
        },
        {"Contents": [{"Key": f"jobs/checkpoints/{job_id}/result.json"}]},
    ]
    service.s3_client.delete_objects.return_value = {}
    assert not S3Service.delete_job_result_artifacts(service, job_id)
    assert [
        call.kwargs["MaxKeys"]
        for call in service.s3_client.list_objects_v2.call_args_list
    ] == [100, 100]
    service.s3_client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": "documents/another-user/source.pdf"}]}
    ]
    service.s3_client.delete_objects.reset_mock()
    with pytest.raises(ValueError, match="namespace_mismatch"):
        S3Service.delete_job_result_artifacts(service, job_id)
    service.s3_client.delete_objects.assert_not_called()
