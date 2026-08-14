from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.jobs.application.contracts import ReflowBlockKind
from pydantic import BaseModel

DocumentReflowStatus = Literal["pending", "processing", "completed", "failed"]


class DocumentReflowBlockResponse(BaseModel):
    id: str
    index: int
    kind: ReflowBlockKind
    source_markdown: str
    heading_level: int | None
    page_number: int | None


class DocumentReflowResponse(BaseModel):
    document_id: UUID
    status: DocumentReflowStatus
    job_id: UUID
    error_code: str | None
    prompt_revision: str | None
    profile_revision: str | None
    warnings: list[str]
    blocks: list[DocumentReflowBlockResponse]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizedDocumentReflowBlock:
    paper_title: str | None
    block: DocumentReflowBlockResponse
