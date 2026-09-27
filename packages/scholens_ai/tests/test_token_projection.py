import base64
import hashlib

import pytest

from scholens_ai.passages import (
    PassageEmbeddingRecord,
    encode_passage_embedding_artifact,
)
from scholens_ai.token_projection import TokenProjection, TokenSpan


def projection(text="alpha beta", spans=None):
    spans = spans or [TokenSpan(start=0, end=len(text), tokens=2)]
    digests = {
        hashlib.sha256(text[s.start : s.end].encode()).hexdigest() for s in spans
    }
    data = encode_passage_embedding_artifact(
        model_revision="test-v1",
        records=[
            PassageEmbeddingRecord(digest, (1.0,) + (0.0,) * 383) for digest in digests
        ],
    )
    return TokenProjection(
        content_digest=hashlib.sha256(text.encode()).hexdigest(),
        model_revision="test-v1",
        spans=spans,
        vectors=base64.b64encode(data).decode(),
    )


def test_projection_keeps_multiple_spans_on_one_line_and_reuses_identical_vectors():
    text = "alpha alpha"
    result = projection(
        text,
        [TokenSpan(start=0, end=5, tokens=1), TokenSpan(start=6, end=11, tokens=1)],
    )
    records = list(result.validated_passages(text))
    assert [(r.start_line, r.end_line, r.content) for r in records] == [
        (1, 1, "alpha"),
        (1, 1, "alpha"),
    ]
    assert records[0].embedding == records[1].embedding


def test_projection_rejects_changed_source_before_any_rows():
    with pytest.raises(ValueError, match="source"):
        list(projection().validated_passages("changed content"))


@pytest.mark.parametrize(
    "change",
    [
        {"model_revision": "different"},
        {"vectors": "not-base64"},
        {"spans": [TokenSpan(start=0, end=200, tokens=1)]},
        {"spans": [TokenSpan(start=0, end=5, tokens=1)]},
        {
            "spans": [
                TokenSpan(start=0, end=10, tokens=1),
                TokenSpan(start=0, end=10, tokens=1),
            ]
        },
    ],
)
def test_projection_rejects_partial_mismatched_or_corrupt_artifacts(change):
    with pytest.raises(ValueError):
        list(projection().model_copy(update=change).validated_passages("alpha beta"))


def test_projection_derives_unicode_line_positions_from_canonical_text():
    text = "中文🙂\n\nsecond line"
    result = projection(
        text,
        [
            TokenSpan(start=0, end=3, tokens=3),
            TokenSpan(start=5, end=len(text), tokens=2),
        ],
    )
    assert [(r.start_line, r.end_line) for r in result.validated_passages(text)] == [
        (1, 1),
        (3, 3),
    ]
