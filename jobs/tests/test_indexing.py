import hashlib
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.indexing import build_checkpointed_projection


class CharacterTokenizer:
    def encode(self, sequence, *, add_special_tokens):
        return SimpleNamespace(
            offsets=[(i, i + 1) for i, c in enumerate(sequence) if not c.isspace()]
        )


class Storage:
    def __init__(self):
        self.objects = {}

    def object_exists(self, key):
        return key in self.objects

    def download_bounded_bytes(self, key, *, max_bytes):
        result = self.objects[key]
        assert len(result) <= max_bytes
        return result

    def upload_bytes_to_key(self, data, key, content_type):
        self.objects[key] = data
        return key


def build(text, storage, model, job_id):
    return build_checkpointed_projection(
        raw_content=text,
        content_digest=hashlib.sha256(text.encode()).hexdigest(),
        job_id=job_id,
        storage=storage,
        embedder=model,
        tokenizer=CharacterTokenizer(),
        check_cancelled=lambda: None,
    )


def model():
    return SimpleNamespace(
        revision="test-v1",
        embed_passages=Mock(
            side_effect=lambda texts: [[1.0] + [0.0] * 383 for _ in texts]
        ),
    )


def test_restart_reuses_checkpoint_vectors_and_retains_duplicate_coordinates():
    storage, embedder, job_id = Storage(), model(), str(uuid4())
    text = "x" * 1200
    first = build(text, storage, embedder, job_id)
    embedder.embed_passages.reset_mock()
    second = build(text, storage, embedder, job_id)
    assert first == second
    embedder.embed_passages.assert_not_called()
    assert len(first.validated_passages(text)) > 1
    assert len(storage.objects) == 1


def test_failed_later_batch_keeps_completed_checkpoints_for_recovery():
    storage, embedder, job_id = Storage(), model(), str(uuid4())
    text = " ".join(f"unique{i:05d}" for i in range(4000))
    original = embedder.embed_passages.side_effect
    calls = 0

    def fail_after_checkpoint(texts):
        nonlocal calls
        calls += 1
        if calls == 9:
            raise RuntimeError("owner_restarted")
        return original(texts)

    embedder.embed_passages.side_effect = fail_after_checkpoint
    with pytest.raises(RuntimeError, match="owner_restarted"):
        build(text, storage, embedder, job_id)
    assert len(storage.objects) == 1
    embedder.embed_passages.side_effect = original
    embedder.embed_passages.reset_mock()
    recovered = build(text, storage, embedder, job_id)
    assert len(recovered.validated_passages(text)) > 64
    unique_count = len({p.source_digest for p in recovered.validated_passages(text)})
    assert embedder.embed_passages.call_count == (unique_count - 64 + 7) // 8


def test_source_mismatch_is_rejected_before_any_inference_or_checkpoint():
    storage, embedder = Storage(), model()
    with pytest.raises(ValueError, match="source"):
        build_checkpointed_projection(
            raw_content="new",
            content_digest="a" * 64,
            job_id=str(uuid4()),
            storage=storage,
            embedder=embedder,
            tokenizer=CharacterTokenizer(),
            check_cancelled=lambda: None,
        )
    embedder.embed_passages.assert_not_called()
    assert not storage.objects


def test_corrupt_checkpoint_is_not_silently_accepted_or_recomputed():
    storage, embedder, job_id = Storage(), model(), str(uuid4())
    build("source text", storage, embedder, job_id)
    key = next(iter(storage.objects))
    storage.objects[key] = b"corrupt"
    embedder.embed_passages.reset_mock()
    with pytest.raises(ValueError):
        build("source text", storage, embedder, job_id)
    embedder.embed_passages.assert_not_called()
