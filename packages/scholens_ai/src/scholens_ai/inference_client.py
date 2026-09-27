"""Deadline-bound Unix socket client; never loads a local model on failure."""

from __future__ import annotations

from collections.abc import Sequence
import socket
import time
from typing import Literal

from scholens_ai.embeddings import EMBEDDING_MODEL_REVISION
from scholens_ai.inference_protocol import (
    FRAME_HEADER,
    MAX_FRAME_BYTES,
    InferenceRequest,
    InferenceResponse,
    frame,
)


class EmbeddingUnavailable(RuntimeError):
    """A stable degradation signal containing no query or document content."""


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
        self._call("health", [], self._query_timeout)

    def _call(
        self,
        kind: Literal["query", "passage", "health"],
        texts: Sequence[str],
        timeout: float,
    ) -> list[list[float]]:
        request = InferenceRequest(
            model_revision=self.revision,
            kind=kind,
            texts=tuple(texts),
            deadline_ms=max(1, int(timeout * 1000)),
        )
        data = frame(request.model_dump_json().encode())
        deadline = time.monotonic() + timeout
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout)
                connection.connect(self._path)
                connection.settimeout(_remaining(deadline))
                connection.sendall(data)
                size = FRAME_HEADER.unpack(
                    _read(connection, FRAME_HEADER.size, deadline)
                )[0]
                if not 0 < size <= MAX_FRAME_BYTES:
                    raise EmbeddingUnavailable("inference_response_bound")
                response = InferenceResponse.model_validate_json(
                    _read(connection, size, deadline)
                )
            if response.model_revision != self.revision:
                raise EmbeddingUnavailable("inference_revision")
            if response.error is not None:
                raise EmbeddingUnavailable(f"inference_{response.error}")
            if len(response.vectors) != len(texts):
                raise EmbeddingUnavailable("inference_response_count")
            return response.vectors
        except (OSError, ValueError) as exc:
            raise EmbeddingUnavailable("inference_unavailable") from exc


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EmbeddingUnavailable("inference_deadline")
    return remaining


def _read(connection: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        connection.settimeout(_remaining(deadline))
        received = connection.recv(size - len(data))
        if not received:
            raise EmbeddingUnavailable("inference_connection_closed")
        data.extend(received)
    return bytes(data)
