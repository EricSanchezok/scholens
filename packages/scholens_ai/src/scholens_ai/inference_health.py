"""Read-only readiness protocol without loading model or validation runtimes."""

import json
import time

from scholens_ai.embedding_contract import EMBEDDING_MODEL_REVISION
from scholens_ai.inference_transport import EmbeddingUnavailable, exchange


def check_health(
    path: str, *, revision: str = EMBEDDING_MODEL_REVISION, timeout: float = 0.75
) -> None:
    if not path or not 1 <= len(revision) <= 128 or not 0 < timeout <= 30:
        raise ValueError("Invalid inference health configuration")
    deadline = time.monotonic() + timeout
    request = json.dumps(
        {
            "model_revision": revision,
            "kind": "health",
            "texts": [],
            "deadline_ms": max(1, int(timeout * 1000)),
        }
    ).encode()
    try:
        response = json.loads(exchange(path, request, deadline))
    except ValueError:
        raise EmbeddingUnavailable("inference_response_invalid") from None
    if not isinstance(response, dict) or response.keys() - {
        "model_revision",
        "vectors",
        "error",
    }:
        raise EmbeddingUnavailable("inference_response_invalid")
    if response.get("model_revision") != revision:
        raise EmbeddingUnavailable("inference_revision")
    if response.get("vectors", []) != [] or response.get("error") is not None:
        raise EmbeddingUnavailable("inference_unhealthy")
