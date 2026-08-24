"""Service-neutral payload contract for generated-object deletion jobs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Sequence

MAX_STORAGE_DELETE_KEY_UTF8_BYTES = 1_024
MAX_STORAGE_DELETE_KEYS_PER_BATCH = 100
MAX_STORAGE_DELETE_BATCH_JSON_BYTES = 64 * 1_024
STORAGE_DELETE_ALLOWED_PREFIXES = ("documents/", "research/audio/")

_SAFE_OBJECT_KEY = re.compile(r"[A-Za-z0-9._/-]+")


def require_storage_delete_key(value: object) -> str:
    """Return one canonical generated-object key or reject it safely."""

    if not isinstance(value, str) or not value:
        raise ValueError("storage_delete_key_invalid")
    if len(value.encode("utf-8")) > MAX_STORAGE_DELETE_KEY_UTF8_BYTES:
        raise ValueError("storage_delete_key_too_large")
    if not value.startswith(STORAGE_DELETE_ALLOWED_PREFIXES):
        raise ValueError("storage_delete_key_namespace_invalid")
    if _SAFE_OBJECT_KEY.fullmatch(value) is None:
        raise ValueError("storage_delete_key_characters_invalid")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise ValueError("storage_delete_key_path_invalid")
    return value


def storage_delete_batch_json_bytes(object_keys: Sequence[str]) -> bytes:
    """Encode the object-key portion exactly for byte-budget decisions."""

    return json.dumps(
        {"object_keys": list(object_keys)},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def storage_delete_batch_digest(object_keys: Sequence[str]) -> str:
    """Return a stable digest for one canonical deletion batch."""

    return hashlib.sha256(storage_delete_batch_json_bytes(object_keys)).hexdigest()


def require_storage_delete_batch(object_keys: object) -> tuple[str, ...]:
    """Validate the exact bounded batch accepted by a deletion worker."""

    if (
        not isinstance(object_keys, Sequence)
        or isinstance(object_keys, (str, bytes, bytearray))
        or not object_keys
    ):
        raise ValueError("storage_delete_batch_invalid")
    validated = tuple(require_storage_delete_key(key) for key in object_keys)
    if len(validated) > MAX_STORAGE_DELETE_KEYS_PER_BATCH:
        raise ValueError("storage_delete_batch_item_limit_exceeded")
    if len(validated) != len(set(validated)):
        raise ValueError("storage_delete_batch_duplicate_key")
    if validated != tuple(sorted(validated)):
        raise ValueError("storage_delete_batch_order_invalid")
    if (
        len(storage_delete_batch_json_bytes(validated))
        > MAX_STORAGE_DELETE_BATCH_JSON_BYTES
    ):
        raise ValueError("storage_delete_batch_byte_limit_exceeded")
    return validated


def chunk_storage_delete_keys(
    object_keys: Iterable[object],
) -> Iterator[tuple[str, ...]]:
    """Stream a producer-ordered unique input using only bounded batch state.

    Producers own global deterministic ordering. Requiring a strictly
    increasing stream proves uniqueness across batch boundaries while retaining
    only the previous key and the current bounded batch.
    """

    current: list[str] = []
    previous_key: str | None = None
    for raw_key in object_keys:
        key = require_storage_delete_key(raw_key)
        if previous_key is not None and key == previous_key:
            raise ValueError("storage_delete_input_duplicate_key")
        if previous_key is not None and key < previous_key:
            raise ValueError("storage_delete_input_order_invalid")
        candidate = (*current, key)
        exceeds_items = len(candidate) > MAX_STORAGE_DELETE_KEYS_PER_BATCH
        exceeds_bytes = (
            len(storage_delete_batch_json_bytes(candidate))
            > MAX_STORAGE_DELETE_BATCH_JSON_BYTES
        )
        if exceeds_items or exceeds_bytes:
            if not current:
                raise ValueError("storage_delete_key_cannot_fit_batch")
            yield tuple(current)
            current = [key]
            require_storage_delete_batch(current)
        else:
            current.append(key)
        previous_key = key
    if current:
        yield tuple(current)


__all__ = [
    "MAX_STORAGE_DELETE_BATCH_JSON_BYTES",
    "MAX_STORAGE_DELETE_KEYS_PER_BATCH",
    "MAX_STORAGE_DELETE_KEY_UTF8_BYTES",
    "STORAGE_DELETE_ALLOWED_PREFIXES",
    "chunk_storage_delete_keys",
    "require_storage_delete_batch",
    "require_storage_delete_key",
    "storage_delete_batch_digest",
    "storage_delete_batch_json_bytes",
]
