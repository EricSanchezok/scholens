"""Strict ownership rules for versioned PDF text-repair artifacts."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping

from app.shared.application.text import json_bounded_prefix
from app.shared.domain import JsonValue

UNICODE_REPAIR_KIND = "unicode_replacement"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REPAIR_REVISION_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_AUDIT_RESULT_FIELDS = frozenset(
    {
        "success",
        "job_id",
        "repair_applied",
        "repair_outcome",
        "current_replacement_count",
        "candidate_replacement_count",
        "candidate_content_sha256",
        "candidate_character_count",
        "candidate_page_count",
        "parser_markdown_s3_key",
        "parser_archive_s3_key",
        "parser_backend",
        "parser_quality",
        "parser_version",
        "parser_warning_code",
        "duration",
    }
)
_AUDIT_BOOLEAN_FIELDS = frozenset({"success", "repair_applied"})
_AUDIT_COUNT_FIELDS = frozenset(
    {
        "current_replacement_count",
        "candidate_replacement_count",
        "candidate_character_count",
        "candidate_page_count",
    }
)
_AUDIT_STRING_JSON_BYTES = {
    "job_id": 128,
    "repair_outcome": 128,
    "parser_markdown_s3_key": 1_024,
    "parser_archive_s3_key": 1_024,
    "parser_backend": 64,
    "parser_quality": 64,
    "parser_version": 256,
    "parser_warning_code": 128,
}


def unicode_repair_artifact_keys(
    *,
    job_id: object,
    payload: object,
) -> tuple[str, ...]:
    """Derive the only storage keys owned by a valid repair-job namespace.

    Callback-supplied object keys are deliberately ignored. This function is
    safe to use for rejection and document-GC cleanup because every component
    comes from the persisted job identity and its validated bounded payload.
    """

    if not isinstance(job_id, uuid.UUID) or not isinstance(payload, Mapping):
        return ()
    revision = payload.get("repair_revision")
    content_sha256 = payload.get("content_sha256")
    if (
        payload.get("repair_kind") != UNICODE_REPAIR_KIND
        or not isinstance(revision, str)
        or _REPAIR_REVISION_PATTERN.fullmatch(revision) is None
        or not isinstance(content_sha256, str)
        or _SHA256_PATTERN.fullmatch(content_sha256) is None
    ):
        return ()
    prefix = f"documents/{content_sha256}/repairs/{revision}/{job_id}/"
    return (f"{prefix}canonical.md", f"{prefix}mineru-result.zip")


def bounded_unicode_repair_audit_result(value: object) -> dict[str, JsonValue]:
    """Remove legacy candidate bodies while retaining bounded repair evidence."""

    if not isinstance(value, Mapping):
        return {"repair_outcome": "legacy_result_sanitized"}
    sanitized: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _AUDIT_RESULT_FIELDS:
            continue
        if key in _AUDIT_BOOLEAN_FIELDS and isinstance(item, bool):
            sanitized[key] = item
        elif (
            key in _AUDIT_COUNT_FIELDS
            and isinstance(item, int)
            and not isinstance(item, bool)
            and 0 <= item < 2**63
        ):
            sanitized[key] = item
        elif (
            key == "candidate_content_sha256"
            and isinstance(item, str)
            and _SHA256_PATTERN.fullmatch(item) is not None
        ):
            sanitized[key] = item
        elif key in _AUDIT_STRING_JSON_BYTES and isinstance(item, str):
            sanitized[key] = json_bounded_prefix(
                item,
                max_bytes=_AUDIT_STRING_JSON_BYTES[key],
            )
        elif (
            key == "duration"
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
            and 0 <= item <= 31_536_000
        ):
            sanitized[key] = item
    if "repair_outcome" not in sanitized:
        sanitized["repair_outcome"] = "legacy_result_sanitized"
    return sanitized


__all__ = [
    "UNICODE_REPAIR_KIND",
    "bounded_unicode_repair_audit_result",
    "unicode_repair_artifact_keys",
]
