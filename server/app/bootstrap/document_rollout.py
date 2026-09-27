"""Stable requester cohorts, evaluated only when new document work is accepted."""

import hashlib


def in_document_rollout(user_id: int, percentage: int) -> bool:
    if not 0 <= percentage <= 100:
        raise ValueError("document rollout percentage must be between 0 and 100")
    bucket = (
        int.from_bytes(
            hashlib.sha256(f"document-pipeline:v1:{user_id}".encode()).digest()[:8],
            "big",
        )
        % 100
    )
    return bucket < percentage
