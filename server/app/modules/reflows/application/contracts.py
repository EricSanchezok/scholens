from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.jobs.application.contracts import (
    ReflowAssetKind,
    ReflowBlockKind,
    ReflowPresentationStatus,
    ReflowSourceRectPayload,
)
from pydantic import BaseModel

DocumentReflowStatus = Literal["pending", "processing", "completed", "failed"]


class DocumentReflowBlockResponse(BaseModel):
    id: str
    index: int
    kind: ReflowBlockKind
    source_markdown: str
    render_markdown: str
    group_id: str | None
    heading_level: int | None
    page_number: int | None
    source_rect: ReflowSourceRectPayload | None
    presentation_status: ReflowPresentationStatus
    asset_id: str | None


class DocumentReflowAssetResponse(BaseModel):
    id: str
    kind: ReflowAssetKind
    content_type: str
    width: int
    height: int
    page_number: int
    source_rect: ReflowSourceRectPayload
    checksum: str


class DocumentReflowAssetUrlResponse(BaseModel):
    asset_id: str
    url: str
    expires_in: int


class DocumentReflowResponse(BaseModel):
    document_id: UUID
    status: DocumentReflowStatus
    job_id: UUID
    error_code: str | None
    prompt_revision: str | None
    profile_revision: str | None
    warnings: list[str]
    blocks: list[DocumentReflowBlockResponse]
    assets: list[DocumentReflowAssetResponse]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizedDocumentReflowBlock:
    paper_title: str | None
    block: DocumentReflowBlockResponse
