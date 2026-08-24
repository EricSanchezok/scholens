"""Authorized canonical paper metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.documents import DocumentResponse
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class PaperDetailsRevision:
    document_id: UUID
    revision: str
    durable_json_utf8_upper_bound: int | None = None


@dataclass(frozen=True, slots=True)
class PaperDetailsResourcePreview:
    document: DocumentResponse
    content_truncated: bool


class PaperDetailsPort(Protocol):
    def get_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsRevision | None: ...

    def get_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsRevision | None: ...

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> DocumentResponse | None: ...

    def get_resource_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> PaperDetailsResourcePreview | None: ...


class GetPaperDetails:
    def __init__(
        self,
        details: PaperDetailsPort,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._details = details
        self._project_documents = project_documents

    def __call__(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> DocumentResponse:
        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        result = self._details.get(actor=actor, document_id=document_id)
        if result is None:
            raise _paper_not_found()
        return result

    def authorize_revision(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperDetailsRevision:
        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        result = self._details.get_revision(actor=actor, document_id=document_id)
        if result is None:
            raise _paper_not_found()
        return result

    def authorize_retained_size(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperDetailsRevision:
        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        result = self._details.get_retained_size(
            actor=actor,
            document_id=document_id,
        )
        if result is None:
            raise _paper_not_found()
        return result

    def resource_preview(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> PaperDetailsResourcePreview:
        """Return a SQL-bounded fallback for historical oversized metadata."""

        self._require_project_document(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        result = self._details.get_resource_preview(
            actor=actor,
            document_id=document_id,
        )
        if result is None:
            raise _paper_not_found()
        return result

    def _require_project_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> None:
        if project_id is not None and document_id not in self._project_documents(
            actor=actor,
            project_id=project_id,
        ):
            raise _paper_not_found()


def _paper_not_found() -> AppError:
    return AppError(
        code="paper_not_found",
        message="Paper not found",
        kind=FailureKind.NOT_FOUND,
    )


__all__ = [
    "GetPaperDetails",
    "PaperDetailsPort",
    "PaperDetailsResourcePreview",
    "PaperDetailsRevision",
]
