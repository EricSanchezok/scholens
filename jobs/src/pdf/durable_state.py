"""Fenced MinerU recovery; a known batch is retained until job checkpoint GC."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.execution_delivery import (
    DeliveryUnavailable,
    FencedExecution,
    current_execution,
)
from src.pdf.models import ParserContentError
from src.pdf.state import MinerUBatchCheckpoint, ParserStateStore, ParserTaskState

MAX_CHECKPOINT_BYTES = 8192


class _Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=512)
    upload_url: str = Field(min_length=1, max_length=6144, pattern=r"^https://")


def _load(execution: FencedExecution) -> _Batch | None:
    raw = execution.load_checkpoint("mineru-batch", max_bytes=MAX_CHECKPOINT_BYTES)
    if raw is None:
        return None
    try:
        return _Batch.model_validate_json(raw)
    except ValidationError as exc:
        raise DeliveryUnavailable("mineru_checkpoint_invalid") from exc


def can_resume_mineru(execution: FencedExecution) -> bool:
    """PDF-only policy. Actual reads also verify the source/credential scope."""
    return _load(execution) is not None


def parser_state_store() -> ParserTaskState:
    execution = current_execution()
    return DurableParserStateStore(execution) if execution else ParserStateStore()


class DurableParserStateStore(ParserStateStore):
    """Keep Redis's submit lock, but never depend on Redis for provider identity.

    Fenced jobs have one immutable batch and a separate monotonic upload marker.
    Keeping the batch through success closes the parse-to-result-persistence gap.
    No marker can authorize submission of a replacement paid batch.
    """

    def __init__(self, execution: FencedExecution) -> None:
        super().__init__()
        self._execution = execution

    async def get_checkpoint(self, job_id: str) -> MinerUBatchCheckpoint | None:
        batch = await asyncio.to_thread(_load, self._execution)
        if batch is None:
            return None
        if batch.scope != job_id:
            raise ParserContentError(
                "MinerU checkpoint scope changed",
                error_code="mineru_checkpoint_scope_changed",
                phase="checkpoint",
            )
        uploaded = await asyncio.to_thread(
            self._execution.load_checkpoint, "mineru-uploaded", max_bytes=16
        )
        if uploaded not in (None, b"true"):
            raise DeliveryUnavailable("mineru_upload_checkpoint_invalid")
        return MinerUBatchCheckpoint(
            batch.batch_id, batch.upload_url, uploaded is not None
        )

    async def save_checkpoint(
        self, job_id: str, checkpoint: MinerUBatchCheckpoint
    ) -> None:
        value = _Batch(
            scope=job_id, batch_id=checkpoint.batch_id, upload_url=checkpoint.upload_url
        )
        existing = await asyncio.to_thread(_load, self._execution)
        if existing is not None and existing != value:
            raise ParserContentError(
                "MinerU checkpoint scope or batch changed",
                error_code="mineru_checkpoint_scope_changed",
                phase="checkpoint",
            )
        if existing is None:
            await asyncio.to_thread(
                self._execution.save_checkpoint,
                "mineru-batch",
                value.model_dump_json().encode(),
                max_bytes=MAX_CHECKPOINT_BYTES,
            )
        if checkpoint.uploaded:
            await asyncio.to_thread(
                self._execution.save_checkpoint,
                "mineru-uploaded",
                b"true",
                max_bytes=16,
            )

    async def clear(self, job_id: str) -> None:
        # Parsing success precedes durable job delivery. GC owns removal.
        self._execution.check_cancelled()
