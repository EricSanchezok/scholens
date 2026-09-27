"""Independent document stage consumers with canonical-source and access fences."""

from uuid import UUID
import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from scholens_ai import TokenProjection, resolve_evidence
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.modules.jobs.application.callbacks import JobHandlerResult, SettleJobUsage
from app.modules.jobs.application.contracts import TokenUsageEventPayload
from app.modules.jobs.application.actions import JOB_CREATED
from app.bootstrap.adapters.document_search_projection import (
    enqueue_metadata_projection,
)
from app.bootstrap.adapters.document_stage_dispatch import enqueue_document_bibliography
from app.modules.jobs.infrastructure.models import JobExecution
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.token_projection import TokenProjectionRepository
from app.shared.application import Actor, OperationContext
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.modules.papers.application.actions import DOCUMENT_METADATA_HYDRATED
from app.modules.papers.infrastructure.repository import document_repository
from app.helpers.parser import parse_publication_date
from app.bootstrap.adapters.research_annotations import create_ai_annotations
from app.modules.operation_journal.domain import OperationChange, ResourceRef
from app.modules.research.application.items import (
    RESEARCH_ANNOTATION_THREAD_CREATED,
    RESEARCH_ANNOTATION_COMMENT_CREATED,
)


def enrichment_update(
    document: Document, metadata: PaperMetadataExtraction, *, job_id: UUID
) -> DocumentUpdate:
    """Fill canonical gaps without replacing human/Zotero values or provenance."""
    values: dict[str, object] = {}
    source = document.raw_content or ""
    digest = document.content_digest or hashlib.sha256(source.encode()).hexdigest()
    candidates = metadata.model_dump(mode="json")
    if metadata.publish_date:
        candidates["publish_date"] = parse_publication_date(metadata.publish_date)
    provenance = dict(document.field_provenance or {})
    for name in (
        "title",
        "authors",
        "abstract",
        "institutions",
        "keywords",
        "publish_date",
        "summary",
    ):
        current, candidate = getattr(document, name), candidates[name]
        filename_placeholder = (
            name == "title"
            and document.title == document.original_filename
            and provenance.get("title") == {"source": "filename"}
        )
        if candidate and (not current or filename_placeholder):
            values[name] = candidate
    if "summary" in values:
        citations = []
        indexes: set[int] = set()
        for citation in metadata.summary_citations:
            if (
                not citation.segment_id
                or citation.index <= 0
                or citation.index in indexes
            ):
                continue
            resolved = resolve_evidence(
                source,
                citation.text,
                segment_id=citation.segment_id,
                content_digest=digest,
            )
            if resolved.anchor is None:
                continue
            indexes.add(citation.index)
            citations.append(
                citation.model_copy(update={"text": resolved.anchor.quote}).model_dump(
                    mode="json"
                )
            )

        def marker(match: re.Match[str]) -> str:
            kept = [
                int(value.strip().lstrip("^"))
                for value in match.group(1).split(",")
                if value.strip().lstrip("^").isdigit()
            ]
            kept = [value for value in kept if value in indexes]
            return "[" + ", ".join(f"^{value}" for value in kept) + "]" if kept else ""

        values["summary"] = re.sub(r"\[\^([0-9,\s^]+)\]", marker, metadata.summary)
        values["summary_citations"] = citations
    update, _dropped = DocumentUpdate.validate_lenient(values)
    if update.model_fields_set:
        provenance.update(
            {
                name: {
                    "source": "document_enrichment",
                    "job_id": str(job_id),
                    "content_digest": digest,
                }
                for name in update.model_fields_set
            }
        )
        update = update.model_copy(update={"field_provenance": provenance})
    return update


class DocumentEnrichmentCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: PaperMetadataExtraction
    usage_events: list[TokenUsageEventPayload] = Field(
        default_factory=list, max_length=32
    )

    @model_validator(mode="after")
    def require_bounded_evidence(self) -> "DocumentEnrichmentCallback":
        if (
            len(self.metadata.highlights) > 64
            or len(self.metadata.summary_citations) > 64
            or len(self.metadata.model_dump_json().encode()) > 256 * 1024
        ):
            raise ValueError("document_enrichment_result_too_large")
        return self


class DocumentEnrichmentCompletion:
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
        if (
            not isinstance(callback, DocumentEnrichmentCallback)
            or callback.task_id != job_id
        ):
            raise ValueError("document_enrichment_callback_mismatch")
        job = job_repository.require(self._db, job_id=job_id)
        if job.payload.get("content_digest") != callback.content_digest:
            raise ValueError("document_enrichment_snapshot_mismatch")
        document = self._db.scalar(
            select(Document)
            .where(
                Document.id == job.document_id,
                accessible_document_condition(user_id=actor.id) if actor else false(),
            )
            .with_for_update()
        )
        if (
            actor is None
            or document is None
            or document.raw_content is None
            or hashlib.sha256(document.raw_content.encode()).hexdigest()
            != callback.content_digest
        ):
            job_repository.fail(
                self._db, job_id=job_id, error_code="document_stage_source_changed"
            )
            return JobHandlerResult(value={"accepted": False})
        update = enrichment_update(document, callback.metadata, job_id=job_id)
        document_repository.update_canonical(
            self._db, document=document, update=update, refresh_result=False
        )
        execution = self._db.get(JobExecution, job_id)
        metadata = callback.metadata.model_copy(
            update={
                "highlights": [h for h in callback.metadata.highlights if h.segment_id]
            }
        )
        annotations = create_ai_annotations(
            self._db,
            document_id=document.id,
            metadata=metadata,
            user=actor,
            source_job_id=job_id,
            execution_generation=execution.claim_generation if execution else None,
        )
        job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "document_id": str(document.id),
                "content_digest": callback.content_digest,
                "evidence_candidates": len(callback.metadata.highlights),
                "evidence_anchored": annotations.anchored,
                "evidence_created": len(annotations.thread_ids),
                "evidence_existing": annotations.already_present,
            },
        )
        changes = (
            [
                OperationChange(
                    action=DOCUMENT_METADATA_HYDRATED,
                    resources=(ResourceRef("document", str(document.id)),),
                )
            ]
            if update.model_fields_set
            else []
        )
        changes.extend(
            OperationChange(
                action=RESEARCH_ANNOTATION_THREAD_CREATED,
                resources=(ResourceRef("research_item", str(identity)),),
            )
            for identity in annotations.thread_ids
        )
        changes.extend(
            OperationChange(
                action=RESEARCH_ANNOTATION_COMMENT_CREATED,
                resources=(ResourceRef("annotation_comment", str(identity)),),
            )
            for identity in annotations.comment_ids
        )
        metadata_index = enqueue_metadata_projection(
            self._db, document=document, actor=actor, operation=operation
        )
        if metadata_index is not None and metadata_index.created:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef("job", str(metadata_index.job.id)),),
                )
            )
        bibliography = enqueue_document_bibliography(
            self._db, document=document, actor=actor, operation=operation
        )
        if bibliography.created:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef("job", str(bibliography.job.id)),),
                )
            )
        return JobHandlerResult(
            value={"accepted": True},
            changes=changes,
            post_commit=(
                SettleJobUsage(user_id=actor.id, events=tuple(callback.usage_events)),
            ),
        )


class DocumentIndexCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    projection: TokenProjection


class DocumentIndexCompletion:
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
            not isinstance(callback, DocumentIndexCallback)
            or callback.task_id != job_id
        ):
            raise ValueError("document_index_callback_mismatch")
        job = job_repository.require(self._db, job_id=job_id)
        projection = callback.projection
        if (
            job.payload.get("content_digest") != projection.content_digest
            or job.payload.get("model_revision") != projection.model_revision
        ):
            raise ValueError("document_index_snapshot_mismatch")
        document_id = self._db.scalar(
            select(Document.id)
            .where(
                Document.id == job.document_id,
                accessible_document_condition(user_id=actor.id)
                if actor is not None
                else false(),
            )
            .with_for_update()
        )
        if document_id is None or not TokenProjectionRepository(self._db).adopt(
            document_id=document_id,
            projection=projection,
        ):
            job_repository.fail(
                self._db, job_id=job_id, error_code="document_stage_source_changed"
            )
            return JobHandlerResult(value={"accepted": False})
        job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "document_id": str(document_id),
                "passage_count": len(projection.spans),
                "content_digest": projection.content_digest,
                "model_revision": projection.model_revision,
            },
        )
        return JobHandlerResult(value={"accepted": True})
