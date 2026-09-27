"""Source-fenced deterministic bibliography snapshots and short result writes."""

from dataclasses import asdict
import hashlib
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.helpers.parser import parse_publication_date
from app.modules.jobs.application.callbacks import JobHandlerResult
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.application.actions import DOCUMENT_METADATA_HYDRATED
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    normalize_citation_metadata_patch,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.domain.citations import CitationFields, fields_from_paper
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.document_loading import DOCUMENT_CITATION_COLUMNS
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.operation_journal.domain import OperationChange, ResourceRef
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import JobOperation


def bibliography_identity(fields: CitationFields) -> str:
    return hashlib.sha256(
        json.dumps(
            asdict(fields), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


class DocumentBibliographyResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch: CitationMetadataPatch = Field(default_factory=CitationMetadataPatch)


class DocumentBibliographyCallback(DocumentBibliographyResolution):
    task_id: UUID


def bibliography_snapshot(
    db: Session, *, job_id: UUID, actor: Actor
) -> tuple[DocumentBibliographyResolution, CitationFields | None]:
    job = job_repository.require(db, job_id=job_id)
    if (
        job.operation != JobOperation.DOCUMENT_BIBLIOGRAPHY.value
        or job.requested_by_id != actor.id
    ):
        raise ValueError("document_bibliography_job_scope_invalid")
    result = DocumentBibliographyResolution.model_validate(
        {
            "content_digest": job.payload.get("content_digest"),
            "identity_digest": job.payload.get("identity_digest"),
        }
    )
    document = db.scalar(
        select(Document)
        .options(
            load_only(
                *DOCUMENT_CITATION_COLUMNS,
                Document.content_digest,
                Document.original_filename,
                raiseload=True,
            )
        )
        .where(
            Document.id == job.document_id,
            accessible_document_condition(user_id=actor.id),
        )
    )
    if document is None or document.content_digest != result.content_digest:
        return result, None
    fields = fields_from_paper(document)
    if bibliography_identity(fields) != result.identity_digest or (
        fields.title == document.original_filename and not fields.doi
    ):
        return result, None
    return result, fields


class DocumentBibliographyCompletion:
    def __init__(self, db: Session) -> None:
        self._db = db

    def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        del operation
        if (
            not isinstance(callback, DocumentBibliographyCallback)
            or callback.task_id != job_id
        ):
            raise ValueError("document_bibliography_callback_mismatch")
        job = job_repository.require(self._db, job_id=job_id)
        if (
            job.payload.get("content_digest") != callback.content_digest
            or job.payload.get("identity_digest") != callback.identity_digest
        ):
            raise ValueError("document_bibliography_snapshot_mismatch")
        document = self._db.scalar(
            select(Document)
            .options(
                load_only(
                    *DOCUMENT_CITATION_COLUMNS,
                    Document.content_digest,
                    Document.original_filename,
                    raiseload=True,
                )
            )
            .where(Document.id == job.document_id)
            .with_for_update()
        )
        allowed = (
            actor is not None
            and self._db.scalar(
                select(Document.id).where(
                    Document.id == job.document_id,
                    accessible_document_condition(user_id=actor.id),
                )
            )
            is not None
        )
        if (
            not allowed
            or document is None
            or document.content_digest != callback.content_digest
            or bibliography_identity(fields_from_paper(document))
            != callback.identity_digest
        ):
            job_repository.fail(
                self._db, job_id=job_id, error_code="document_stage_source_changed"
            )
            return JobHandlerResult(value={"accepted": False})
        patch, _dropped = normalize_citation_metadata_patch(callback.patch)
        values: dict[str, object] = {
            name: value
            for name, value in asdict(patch).items()
            if name != "field_provenance" and value and not getattr(document, name)
        }
        if values.get("publish_date"):
            values["publish_date"] = parse_publication_date(str(values["publish_date"]))
        if values:
            provenance = dict(document.field_provenance or {})
            provenance.update(
                {
                    name: {"source": "bibliography", "job_id": str(job_id)}
                    for name in values
                }
            )
            values["field_provenance"] = provenance
        update = DocumentUpdate.model_validate(values)
        document_repository.update_canonical(
            self._db, document=document, update=update, refresh_result=False
        )
        job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "document_id": str(document.id),
                "fields_updated": [
                    name for name in values if name != "field_provenance"
                ],
            },
        )
        changes = (
            (
                OperationChange(
                    action=DOCUMENT_METADATA_HYDRATED,
                    resources=(ResourceRef("document", str(document.id)),),
                ),
            )
            if values
            else ()
        )
        return JobHandlerResult(value={"accepted": True}, changes=changes)
