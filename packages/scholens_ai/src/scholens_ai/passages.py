"""Deterministic passage windows and a safe cross-service embedding artifact."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct
from collections.abc import Sequence

from scholens_ai.embeddings import EMBEDDING_DIMENSION

PASSAGE_WINDOW_LINES = 5
PASSAGE_STRIDE_LINES = 3
PASSAGE_EMBEDDING_BATCH_SIZE = 128
MAX_PASSAGE_EMBEDDINGS = 10_000
MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES = 16 * 1024 * 1024
_ARTIFACT_MAGIC = b"SPEMB001"
_HEADER = struct.Struct("<8sHHI")
_DIGEST_BYTES = 32


@dataclass(frozen=True, slots=True)
class DocumentPassageWindow:
    start_line: int
    end_line: int
    content: str

    @property
    def source_digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PassageEmbeddingRecord:
    source_digest: str
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedPassageEmbeddingArtifact:
    model_revision: str
    dimension: int
    records: tuple[PassageEmbeddingRecord, ...]


def build_document_passages(
    raw_content: str,
    *,
    window: int = PASSAGE_WINDOW_LINES,
    stride: int = PASSAGE_STRIDE_LINES,
) -> tuple[DocumentPassageWindow, ...]:
    if window < 1 or stride < 1:
        raise ValueError("passage window and stride must be positive")
    sanitized = raw_content.replace("\x00", "")
    lines = sanitized.split("\n")
    return tuple(
        DocumentPassageWindow(
            start_line=index + 1,
            end_line=index + len(lines[index : index + window]),
            content="\n".join(lines[index : index + window]),
        )
        for index in range(0, len(lines), stride)
    )


def encode_passage_embedding_artifact(
    *,
    model_revision: str,
    records: Sequence[PassageEmbeddingRecord],
) -> bytes:
    revision = model_revision.encode("utf-8")
    if not revision or len(revision) > 128:
        raise ValueError("invalid passage embedding model revision")
    if len(records) > MAX_PASSAGE_EMBEDDINGS:
        raise ValueError("too many passage embeddings")
    output = bytearray(
        _HEADER.pack(
            _ARTIFACT_MAGIC,
            len(revision),
            EMBEDDING_DIMENSION,
            len(records),
        )
    )
    output.extend(revision)
    vector = struct.Struct(f"<{EMBEDDING_DIMENSION}f")
    for record in records:
        if len(record.source_digest) != 64:
            raise ValueError("invalid passage source digest")
        try:
            digest = bytes.fromhex(record.source_digest)
        except ValueError as exc:
            raise ValueError("invalid passage source digest") from exc
        if len(record.embedding) != EMBEDDING_DIMENSION or not all(
            math.isfinite(value) for value in record.embedding
        ):
            raise ValueError("invalid passage embedding")
        norm = math.sqrt(sum(value * value for value in record.embedding))
        if not 0.9 <= norm <= 1.1:
            raise ValueError("passage embedding must be normalized")
        output.extend(digest)
        output.extend(vector.pack(*record.embedding))
        if len(output) > MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES:
            raise ValueError("passage embedding artifact is too large")
    return bytes(output)


def decode_passage_embedding_artifact(
    data: bytes,
) -> DecodedPassageEmbeddingArtifact:
    if len(data) > MAX_PASSAGE_EMBEDDING_ARTIFACT_BYTES:
        raise ValueError("passage embedding artifact is too large")
    if len(data) < _HEADER.size:
        raise ValueError("passage embedding artifact is truncated")
    magic, revision_size, dimension, count = _HEADER.unpack_from(data)
    if magic != _ARTIFACT_MAGIC or dimension != EMBEDDING_DIMENSION:
        raise ValueError("passage embedding artifact header is invalid")
    if revision_size < 1 or revision_size > 128 or count > MAX_PASSAGE_EMBEDDINGS:
        raise ValueError("passage embedding artifact header is invalid")
    record_size = _DIGEST_BYTES + dimension * 4
    expected_size = _HEADER.size + revision_size + count * record_size
    if len(data) != expected_size:
        raise ValueError("passage embedding artifact size is invalid")
    offset = _HEADER.size
    try:
        revision = data[offset : offset + revision_size].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("passage embedding model revision is invalid") from exc
    offset += revision_size
    vector = struct.Struct(f"<{dimension}f")
    records: list[PassageEmbeddingRecord] = []
    digests: set[str] = set()
    for _ in range(count):
        digest = data[offset : offset + _DIGEST_BYTES].hex()
        offset += _DIGEST_BYTES
        embedding = tuple(vector.unpack_from(data, offset))
        offset += vector.size
        if digest in digests:
            raise ValueError("passage embedding artifact contains duplicate digests")
        if not all(math.isfinite(value) for value in embedding):
            raise ValueError("passage embedding artifact contains non-finite values")
        norm = math.sqrt(sum(value * value for value in embedding))
        if not 0.9 <= norm <= 1.1:
            raise ValueError("passage embedding artifact contains unnormalized values")
        digests.add(digest)
        records.append(
            PassageEmbeddingRecord(source_digest=digest, embedding=embedding)
        )
    return DecodedPassageEmbeddingArtifact(
        model_revision=revision,
        dimension=dimension,
        records=tuple(records),
    )
