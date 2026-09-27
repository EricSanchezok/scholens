"""Provider recovery survives Redis loss without creating a second paid batch."""

import asyncio
import hashlib
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.execution_delivery import DeliveryUnavailable, ExecutionLost, FencedExecution
from src.pdf.durable_state import DurableParserStateStore, can_resume_mineru
from src.pdf.models import ParserContentError
from src.pdf.mineru import MinerUClient, MinerUConfig
from src.pdf.state import MinerUBatchCheckpoint


def runtime_and_store():
    objects = {}
    storage = MagicMock()
    storage.object_exists.side_effect = lambda key: key in objects
    storage.download_bounded_bytes.side_effect = lambda key, **_: objects[key]
    storage.upload_bytes_to_key.side_effect = lambda data, key, _: objects.update(
        {key: data}
    )
    job_id = str(uuid4())
    runtime = FencedExecution(
        job_id=job_id,
        base_url=f"https://server/internal/v1/jobs/{job_id}",
        storage=storage,
    )
    runtime.generation = 1
    return runtime, DurableParserStateStore(runtime), objects


def test_known_batch_survives_cleanup_redis_loss_and_generation_takeover():
    async def scenario():
        runtime, store, _ = runtime_and_store()
        scope = hashlib.sha256(b"job:source:credential").hexdigest()
        checkpoint = MinerUBatchCheckpoint("known-batch", "https://upload.example/p")
        assert not can_resume_mineru(runtime)
        await store.save_checkpoint(scope, checkpoint)
        await store.mark_uploaded(scope)
        await store.clear(scope)  # Success precedes final result persistence.
        await store.close()
        runtime.generation = 2
        replacement = DurableParserStateStore(runtime)
        assert can_resume_mineru(runtime)
        restored = await replacement.get_checkpoint(scope)
        assert restored == MinerUBatchCheckpoint(
            "known-batch", "https://upload.example/p", uploaded=True
        )
        # A late old writer cannot regress the independent uploaded marker.
        await replacement.save_checkpoint(scope, checkpoint)
        assert (await replacement.get_checkpoint(scope)).uploaded
        with pytest.raises(ParserContentError, match="scope"):
            await replacement.get_checkpoint(hashlib.sha256(b"changed").hexdigest())
        await replacement.close()

    asyncio.run(scenario())


def test_corrupt_or_oversized_checkpoint_cannot_authorize_paid_recovery():
    runtime, _, objects = runtime_and_store()
    key = f"jobs/checkpoints/{runtime.job_id}/mineru-batch.json"
    for value in (b"{", b"x" * 9000, json.dumps({"scope": "x"}).encode()):
        objects[key] = value
        with pytest.raises(DeliveryUnavailable):
            can_resume_mineru(runtime)


def test_lost_fence_cannot_read_or_save_provider_checkpoint():
    runtime, store, objects = runtime_and_store()
    runtime._lost.set()
    with pytest.raises(ExecutionLost):
        asyncio.run(
            store.save_checkpoint(
                "a" * 64, MinerUBatchCheckpoint("x", "https://e.co/p")
            )
        )
    with pytest.raises(ExecutionLost):
        can_resume_mineru(runtime)
    assert not objects


def test_restarted_client_reuses_durable_batch_without_provider_submission():
    async def scenario():
        runtime, store, _ = runtime_and_store()
        scope = "a" * 64
        checkpoint = MinerUBatchCheckpoint(
            "existing-batch", "https://upload.example/p", True
        )
        await store.save_checkpoint(scope, checkpoint)
        await store.close()
        runtime.generation = 2
        with patch(
            "src.pdf.mineru.parser_state_store",
            return_value=DurableParserStateStore(runtime),
        ):
            client = MinerUClient(MinerUConfig.from_runtime(token="test-token"))
        with (
            patch.object(client, "request_upload") as submit,
            patch("src.pdf.mineru.begin_scoped_external_effect") as intent,
        ):
            async with client._api_client() as http:
                assert (
                    await client._get_or_create_batch(http, data_id=scope) == checkpoint
                )
            submit.assert_not_called()
            intent.assert_not_called()
        await client.close()

    asyncio.run(scenario())
