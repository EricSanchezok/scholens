"""Consumer-first contract for targeted canonical PDF text repair."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

PDF_TEXT_REPAIR_TASK_NAME = "repair_pdf_text"
PDF_TEXT_REPAIR_MAX_ATTEMPTS = 3

_CANONICAL_SOURCE_KEY = re.compile(r"documents/[0-9a-f]{64}/source\.pdf")
_CONTENT_DIGEST = re.compile(r"[0-9a-f]{64}")
_REPAIR_REVISION = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class PDFTextRepairTaskKwargs(TypedDict):
    """Exact serialized kwargs accepted by the repair Celery consumer."""

    job_id: str
    document_id: str
    s3_key: str
    callback_url: str
    claim_url: str
    progress_url: str
    mineru_credential_url: str
    repair_revision: str
    source_job_id: str
    source_content_digest: str
    repair_attempt: int


def _require_canonical_uuid(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{field} must use canonical UUID form")


def _require_internal_url(value: str, *, field: str) -> None:
    # Endpoint authority and signatures remain transport-owned. This shared
    # contract only excludes missing or unbounded serialized values.
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError(f"{field} must contain a bounded internal URL")


@dataclass(frozen=True, slots=True)
class PDFTextRepairTaskRequest:
    """Validated service-neutral envelope for one text-only repair attempt."""

    job_id: str
    document_id: str
    s3_key: str
    callback_url: str
    claim_url: str
    progress_url: str
    mineru_credential_url: str
    repair_revision: str
    source_job_id: str
    source_content_digest: str
    repair_attempt: int

    def __post_init__(self) -> None:
        _require_canonical_uuid(self.job_id, field="job_id")
        _require_canonical_uuid(self.document_id, field="document_id")
        _require_canonical_uuid(self.source_job_id, field="source_job_id")
        if (
            not isinstance(self.s3_key, str)
            or _CANONICAL_SOURCE_KEY.fullmatch(self.s3_key) is None
        ):
            raise ValueError("s3_key must identify one canonical PDF source")
        for field, value in (
            ("callback_url", self.callback_url),
            ("claim_url", self.claim_url),
            ("progress_url", self.progress_url),
            ("mineru_credential_url", self.mineru_credential_url),
        ):
            _require_internal_url(value, field=field)
        if (
            not isinstance(self.repair_revision, str)
            or _REPAIR_REVISION.fullmatch(self.repair_revision) is None
        ):
            raise ValueError("repair_revision is invalid")
        if (
            not isinstance(self.source_content_digest, str)
            or _CONTENT_DIGEST.fullmatch(self.source_content_digest) is None
        ):
            raise ValueError("source_content_digest must be a lowercase SHA-256 digest")
        if (
            isinstance(self.repair_attempt, bool)
            or not isinstance(self.repair_attempt, int)
            or not 1 <= self.repair_attempt <= PDF_TEXT_REPAIR_MAX_ATTEMPTS
        ):
            raise ValueError(
                f"repair_attempt must be between 1 and {PDF_TEXT_REPAIR_MAX_ATTEMPTS}"
            )

    def as_task_kwargs(self) -> PDFTextRepairTaskKwargs:
        """Return the exact JSON-safe shape submitted to Celery."""
        return {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "s3_key": self.s3_key,
            "callback_url": self.callback_url,
            "claim_url": self.claim_url,
            "progress_url": self.progress_url,
            "mineru_credential_url": self.mineru_credential_url,
            "repair_revision": self.repair_revision,
            "source_job_id": self.source_job_id,
            "source_content_digest": self.source_content_digest,
            "repair_attempt": self.repair_attempt,
        }


__all__ = [
    "PDF_TEXT_REPAIR_MAX_ATTEMPTS",
    "PDF_TEXT_REPAIR_TASK_NAME",
    "PDFTextRepairTaskKwargs",
    "PDFTextRepairTaskRequest",
]
