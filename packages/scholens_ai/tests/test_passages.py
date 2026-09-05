from __future__ import annotations

import pytest

from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    PassageEmbeddingRecord,
    build_document_passages,
    decode_passage_embedding_artifact,
    encode_passage_embedding_artifact,
)


def _normalized_embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


def test_passage_windows_are_stable_and_line_addressable() -> None:
    passages = build_document_passages("one\ntwo\nthree\nfour\nfive\nsix")

    assert [(item.start_line, item.end_line) for item in passages] == [(1, 5), (4, 6)]
    assert passages[0].content == "one\ntwo\nthree\nfour\nfive"
    assert len(passages[0].source_digest) == 64


def test_passage_embedding_artifact_round_trips_without_pickle() -> None:
    passage = build_document_passages("grounded multilingual evidence")[0]
    encoded = encode_passage_embedding_artifact(
        model_revision=EMBEDDING_MODEL_REVISION,
        records=(
            PassageEmbeddingRecord(
                source_digest=passage.source_digest,
                embedding=_normalized_embedding(),
            ),
        ),
    )

    decoded = decode_passage_embedding_artifact(encoded)

    assert decoded.model_revision == EMBEDDING_MODEL_REVISION
    assert decoded.dimension == 384
    assert decoded.records[0].source_digest == passage.source_digest
    assert decoded.records[0].embedding == _normalized_embedding()


@pytest.mark.parametrize("payload", [b"", b"SPEMB001", b"not-an-artifact"])
def test_passage_embedding_artifact_rejects_malformed_bytes(payload: bytes) -> None:
    with pytest.raises(ValueError):
        decode_passage_embedding_artifact(payload)
