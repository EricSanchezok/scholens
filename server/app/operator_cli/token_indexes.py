"""Deterministic repair compute. The caller owns its process budget and transactions."""

import base64
import hashlib

from scholens_ai import (
    TextEmbedder,
    TokenProjection,
    TokenSpan,
    PassageEmbeddingRecord,
    iter_token_passages,
    encode_passage_embedding_artifact,
)
from scholens_ai.token_passages import OffsetTokenizer


def build_repair_projection(
    raw_content: str, *, model: TextEmbedder, tokenizer: OffsetTokenizer
) -> TokenProjection:
    passages = tuple(iter_token_passages(raw_content, tokenizer))
    unique = tuple({p.source_digest: p for p in passages}.values())
    records: list[PassageEmbeddingRecord] = []
    for offset in range(0, len(unique), 8):
        batch = unique[offset : offset + 8]
        vectors = model.embed_passages([p.content for p in batch])
        records.extend(
            PassageEmbeddingRecord(p.source_digest, tuple(v))
            for p, v in zip(batch, vectors, strict=True)
        )
    artifact = encode_passage_embedding_artifact(
        model_revision=model.revision, records=records
    )
    return TokenProjection(
        content_digest=hashlib.sha256(raw_content.encode()).hexdigest(),
        model_revision=model.revision,
        spans=[
            TokenSpan(start=p.start_offset, end=p.end_offset, tokens=p.token_count)
            for p in passages
        ],
        vectors=base64.b64encode(artifact).decode("ascii"),
    )
