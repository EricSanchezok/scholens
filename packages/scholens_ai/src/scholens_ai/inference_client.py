"""Deadline-bound Unix socket client; never loads a local model on failure."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
import time
from typing import Literal

from scholens_ai.embedding_contract import EMBEDDING_MODEL_REVISION
from scholens_ai.inference_protocol import (
    MAX_FRAME_BYTES,
    InferenceRequest,
    InferenceResponse,
)

from scholens_ai.inference_health import check_health
from scholens_ai.inference_transport import (
    EmbeddingUnavailable as EmbeddingUnavailable,
    exchange,
    remaining,
)


class SocketTextEmbedder:
    def __init__(
        self,
        path: str,
        *,
        revision: str = EMBEDDING_MODEL_REVISION,
        query_timeout: float = 0.75,
        passage_timeout: float = 30.0,
    ) -> None:
        if not path or not 0 < query_timeout <= 30 or not 0 < passage_timeout <= 30:
            raise ValueError("Invalid inference socket configuration")
        self._path = path
        self._revision = revision
        self._query_timeout = query_timeout
        self._passage_timeout = passage_timeout

    @property
    def revision(self) -> str:
        return self._revision

    def embed_query(self, text: str) -> list[float]:
        return self._call("query", [text], self._query_timeout)[0]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._call("passage", texts, self._passage_timeout)

    def health(self) -> None:
        check_health(self._path, revision=self.revision, timeout=self._query_timeout)

    def _call(
        self,
        kind: Literal["query", "passage", "health"],
        texts: Sequence[str],
        timeout: float,
    ) -> list[list[float]]:
        deadline = time.monotonic() + timeout
        try:
            request = InferenceRequest(
                model_revision=self.revision,
                kind=kind,
                texts=tuple(texts),
                deadline_ms=max(1, int(timeout * 1000)),
            )
            vectors = []
            for bounded in _bounded_requests(request):
                vectors.extend(self._exchange(bounded, deadline))
            return vectors
        except ValueError:
            # Validation/encoding errors may contain the private input text.
            raise EmbeddingUnavailable("inference_request_invalid") from None

    def _exchange(
        self, request: InferenceRequest, deadline: float
    ) -> list[list[float]]:
        request = request.model_copy(
            update={"deadline_ms": max(1, int(remaining(deadline) * 1000))}
        )
        try:
            response = InferenceResponse.model_validate_json(
                exchange(self._path, request.model_dump_json().encode(), deadline)
            )
            if response.model_revision != self.revision:
                raise EmbeddingUnavailable("inference_revision")
            if response.error is not None:
                raise EmbeddingUnavailable(f"inference_{response.error}")
            if len(response.vectors) != len(request.texts):
                raise EmbeddingUnavailable("inference_response_count")
            return response.vectors
        except ValueError as exc:
            raise EmbeddingUnavailable("inference_unavailable") from exc


def _bounded_requests(request: InferenceRequest) -> Iterator[InferenceRequest]:
    # Character limits do not bound UTF-8 bytes or JSON control-character escapes.
    # Subrequests retain the same absolute client deadline and source order.
    if len(request.model_dump_json().encode()) <= MAX_FRAME_BYTES:
        yield request
        return
    if request.kind != "passage" or len(request.texts) < 2:
        raise EmbeddingUnavailable("inference_request_bound")
    middle = len(request.texts) // 2
    for texts in (request.texts[:middle], request.texts[middle:]):
        yield from _bounded_requests(request.model_copy(update={"texts": texts}))
