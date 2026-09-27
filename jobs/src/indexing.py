"""Checkpointed deterministic index computation; no provider credentials."""

from collections.abc import Callable
import base64
import hashlib
from uuid import UUID

from scholens_ai import (
    PassageEmbeddingRecord,
    TextEmbedder,
    TokenProjection,
    TokenSpan,
    decode_passage_embedding_artifact,
    encode_passage_embedding_artifact,
    iter_token_passages,
    TOKEN_PASSAGE_REVISION,
)
from scholens_ai.token_passages import OffsetTokenizer
from src.execution_delivery import ResultStorage

CHECKPOINT_PASSAGES = 64
INFERENCE_BATCH_SIZE = 8
MAX_CHECKPOINT_BYTES = 128 * 1024


def build_checkpointed_projection(
    *,
    raw_content: str,
    content_digest: str,
    job_id: str,
    storage: ResultStorage,
    embedder: TextEmbedder,
    tokenizer: OffsetTokenizer,
    check_cancelled: Callable[[], None],
) -> TokenProjection:
    if hashlib.sha256(raw_content.encode()).hexdigest() != content_digest:
        raise ValueError("document_index_source_changed")
    job_id = str(UUID(job_id))
    check_cancelled()
    passages = []
    for passage in iter_token_passages(raw_content, tokenizer):
        check_cancelled()
        passages.append(passage)
    unique = tuple({p.source_digest: p for p in passages}.values())
    records: list[PassageEmbeddingRecord] = []
    for offset in range(0, len(unique), CHECKPOINT_PASSAGES):
        check_cancelled()
        batch = unique[offset : offset + CHECKPOINT_PASSAGES]
        identity = hashlib.sha256(
            (
                embedder.revision
                + ":"
                + TOKEN_PASSAGE_REVISION
                + ":"
                + ":".join(p.source_digest for p in batch)
            ).encode()
        ).hexdigest()
        key = f"jobs/checkpoints/{job_id}/index/{identity}.bin"
        if storage.object_exists(key):
            checkpoint = decode_passage_embedding_artifact(
                storage.download_bounded_bytes(key, max_bytes=MAX_CHECKPOINT_BYTES)
            )
            if checkpoint.model_revision != embedder.revision or [
                r.source_digest for r in checkpoint.records
            ] != [p.source_digest for p in batch]:
                raise ValueError("document_index_checkpoint_mismatch")
            records.extend(checkpoint.records)
            continue
        completed: list[PassageEmbeddingRecord] = []
        for start in range(0, len(batch), INFERENCE_BATCH_SIZE):
            check_cancelled()
            inputs = batch[start : start + INFERENCE_BATCH_SIZE]
            embeddings = embedder.embed_passages([p.content for p in inputs])
            completed.extend(
                PassageEmbeddingRecord(p.source_digest, tuple(vector))
                for p, vector in zip(inputs, embeddings, strict=True)
            )
        check_cancelled()
        artifact = encode_passage_embedding_artifact(
            model_revision=embedder.revision, records=completed
        )
        storage.upload_bytes_to_key(
            artifact, key, "application/vnd.scholens.passage-embeddings-v1"
        )
        records.extend(completed)
    check_cancelled()
    artifact = encode_passage_embedding_artifact(
        model_revision=embedder.revision, records=records
    )
    return TokenProjection(
        content_digest=content_digest,
        model_revision=embedder.revision,
        spans=[
            TokenSpan(start=p.start_offset, end=p.end_offset, tokens=p.token_count)
            for p in passages
        ],
        vectors=base64.b64encode(artifact).decode("ascii"),
    )
