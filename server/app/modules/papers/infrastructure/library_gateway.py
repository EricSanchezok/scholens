"""SQLAlchemy/S3 adapters for the personal Library capability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.helpers.s3 import s3_service
from app.database.models import DurableJob
from app.modules.papers.application.contracts.documents import (
    DocumentResponse,
    LibraryPaperResponse,
    LibraryPaperIngestionResponse,
    LibraryPaperListEntry,
    LibraryPaperListIngestionEntry,
    LibraryPaperListPaperEntry,
    LibraryPaperSort,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
)
from app.modules.papers.application.library import (
    LibraryPageDirection,
    LibraryPagePosition,
    LibraryPaperAttachment,
    LibraryPaperPage,
    LibraryPaperRemoval,
    LibraryPaperUpdateResult,
    PublicShare,
)
from app.modules.papers.infrastructure.models import (
    Document,
    LibraryPaper,
    UploadReservation,
)
from app.modules.papers.infrastructure.models import LibraryPaperTag
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.domain.enums import JobStatus
from app.shared.domain.enums import PaperStatus
from app.modules.jobs.application.failures import actionable_job_failure
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload


def document_response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(
        {
            "document_id": document.id,
            "original_filename": document.original_filename,
            "mime_type": document.mime_type,
            "size_bytes": document.size_bytes,
            "title": document.title,
            "authors": document.authors,
            "abstract": document.abstract,
            "institutions": document.institutions,
            "keywords": document.keywords,
            "doi": document.doi,
            "journal": document.journal,
            "publisher": document.publisher,
            "publish_date": document.publish_date,
            "summary": document.summary,
            "summary_citations": document.summary_citations,
            "starter_questions": document.starter_questions,
            "processing_status": document.processing_status,
            "parser_quality": document.parser_quality,
            "parser_warning_code": document.parser_warning_code,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }
    )


def _library_paper_payload(entry: LibraryPaper) -> dict[str, Any]:
    return {
        "library_entry_id": entry.id,
        "user_id": entry.user_id,
        "status": entry.status,
        "last_accessed_at": entry.last_accessed_at,
        "metadata_overrides": entry.metadata_overrides,
        "is_public": entry.is_public,
        "preview_url": (
            s3_service.generate_presigned_url(entry.document.preview_s3_key)
            if entry.document.preview_s3_key
            else None
        ),
        "tags": [
            {"id": tag.id, "name": tag.name, "color": tag.color} for tag in entry.tags
        ],
        "document": document_response(entry.document),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def library_paper_response(entry: LibraryPaper) -> LibraryPaperResponse:
    return LibraryPaperResponse.model_validate(_library_paper_payload(entry))


def library_paper_list_response(entry: LibraryPaper) -> LibraryPaperListPaperEntry:
    return LibraryPaperListPaperEntry.model_validate(_library_paper_payload(entry))


def library_ingestion_response(
    reservation: UploadReservation,
) -> LibraryPaperIngestionResponse:
    job = reservation.job
    stages = {
        "downloading",
        "parsing",
        "extracting_metadata",
        "indexing",
        "finalizing",
    }
    if job.status == JobStatus.RUNNING.value:
        state = "processing"
        stage = job.progress_code if job.progress_code in stages else "parsing"
    elif job.status == JobStatus.FAILED.value:
        state = "failed"
        stage = job.progress_code if job.progress_code in stages else "queued"
    else:
        state, stage = "queued", "queued"
    return LibraryPaperIngestionResponse.model_validate(
        {
            "id": job.id,
            "display_name": reservation.display_name,
            "source_kind": reservation.source_kind,
            "state": state,
            "stage": stage,
            "project_id": job.project_id,
            "document_id": job.document_id,
            "failure": actionable_job_failure(job.error_code),
            "created_at": job.created_at,
        }
    )


class DocumentGcSchedule(Protocol):
    @property
    def job_id(self) -> UUID: ...

    @property
    def created(self) -> bool: ...


class DocumentRemoved(Protocol):
    def __call__(
        self,
        *,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> DocumentGcSchedule | None: ...


class PersonalAnnotationsRemoved(Protocol):
    def __call__(self, *, document_id: UUID, user_id: int) -> None: ...


class SqlAlchemyPaperLibraryGateway:
    def __init__(
        self,
        db: Session,
        *,
        document_removed: DocumentRemoved,
        personal_annotations_removed: PersonalAnnotationsRemoved,
    ) -> None:
        self._db = db
        self._document_removed = document_removed
        self._personal_annotations_removed = personal_annotations_removed

    def list(
        self,
        *,
        user_id: int,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        statuses: tuple[PaperStatus, ...] = (),
        sort: LibraryPaperSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryPaperPage:
        title = func.lower(
            func.coalesce(
                LibraryPaper.metadata_overrides["title"].astext,
                Document.title,
                Document.original_filename,
            )
        )
        if sort in {LibraryPaperSort.ADDED_ASC, LibraryPaperSort.ADDED_DESC}:
            key: Any = LibraryPaper.created_at
            cursor_key: Any = (
                datetime.fromisoformat(position.key) if position is not None else None
            )
            natural_ascending = sort is LibraryPaperSort.ADDED_ASC
        elif sort is LibraryPaperSort.LAST_ACCESSED_DESC:
            key = LibraryPaper.last_accessed_at
            cursor_key = (
                datetime.fromisoformat(position.key) if position is not None else None
            )
            natural_ascending = False
        elif sort in {
            LibraryPaperSort.PUBLISHED_ASC,
            LibraryPaperSort.PUBLISHED_DESC,
        }:
            sentinel = (
                datetime.max if sort is LibraryPaperSort.PUBLISHED_ASC else datetime.min
            )
            key = func.coalesce(Document.publish_date, sentinel)
            cursor_key = (
                datetime.fromisoformat(position.key) if position is not None else None
            )
            natural_ascending = sort is LibraryPaperSort.PUBLISHED_ASC
        else:
            key = title
            cursor_key = position.key if position is not None else None
            natural_ascending = True

        filters = [LibraryPaper.user_id == user_id]
        if query is not None:
            pattern = f"%{query.lower()}%"
            filters.append(
                or_(
                    title.like(pattern),
                    func.lower(func.coalesce(Document.abstract, "")).like(pattern),
                    func.lower(func.coalesce(Document.doi, "")).like(pattern),
                    func.lower(func.array_to_string(Document.authors, " ")).like(
                        pattern
                    ),
                )
            )
        if tag_ids:
            filters.append(
                LibraryPaper.id.in_(
                    select(LibraryPaperTag.library_paper_id).where(
                        LibraryPaperTag.tag_id.in_(tag_ids)
                    )
                )
            )
        if statuses:
            filters.append(
                LibraryPaper.status.in_([status.value for status in statuses])
            )

        active_standalone_reservations: list[UploadReservation] = []
        if not tag_ids and not statuses:
            reservation_filters = [
                DurableJob.requested_by_id == user_id,
                DurableJob.project_id.is_(None),
                DurableJob.status.in_(
                    [
                        JobStatus.PENDING.value,
                        JobStatus.RUNNING.value,
                        JobStatus.FAILED.value,
                    ]
                ),
                UploadReservation.superseded_by_id.is_(None),
                or_(
                    DurableJob.document_id.is_(None),
                    ~exists(
                        select(LibraryPaper.id).where(
                            LibraryPaper.user_id == user_id,
                            LibraryPaper.document_id == DurableJob.document_id,
                        )
                    ),
                ),
            ]
            if query is not None:
                reservation_filters.append(
                    func.lower(UploadReservation.display_name).like(
                        f"%{query.lower()}%"
                    )
                )
            active_standalone_reservations = list(
                self._db.scalars(
                    select(UploadReservation)
                    .join(DurableJob, DurableJob.id == UploadReservation.id)
                    .options(selectinload(UploadReservation.job))
                    .where(*reservation_filters)
                    .order_by(DurableJob.created_at.desc(), DurableJob.id.desc())
                ).all()
            )

        count_statement = (
            select(func.count(LibraryPaper.id))
            .join(Document, Document.id == LibraryPaper.document_id)
            .where(*filters)
        )
        paper_count = int(self._db.scalar(count_statement) or 0)
        total_count = paper_count + len(active_standalone_reservations)

        visible_standalone_reservations = (
            active_standalone_reservations
            if position is None and direction is LibraryPageDirection.FORWARD
            else []
        )

        effective_ascending = (
            natural_ascending
            if direction is LibraryPageDirection.FORWARD
            else not natural_ascending
        )
        if position is not None and cursor_key is not None:
            if effective_ascending:
                filters.append(
                    or_(
                        key > cursor_key,
                        and_(key == cursor_key, LibraryPaper.id > position.id),
                    )
                )
            else:
                filters.append(
                    or_(
                        key < cursor_key,
                        and_(key == cursor_key, LibraryPaper.id < position.id),
                    )
                )

        order = key.asc() if effective_ascending else key.desc()
        id_order = (
            LibraryPaper.id.asc() if effective_ascending else LibraryPaper.id.desc()
        )
        paper_limit = max(0, limit - len(visible_standalone_reservations))
        entries = list(
            self._db.scalars(
                select(LibraryPaper)
                .join(Document, Document.id == LibraryPaper.document_id)
                .options(
                    selectinload(LibraryPaper.document),
                    selectinload(LibraryPaper.tags),
                )
                .where(*filters)
                .order_by(order, id_order)
                .limit(paper_limit + 1)
            ).all()
        )
        has_more = len(entries) > paper_limit
        entries = entries[:paper_limit]
        if direction is LibraryPageDirection.BACKWARD:
            entries.reverse()
        reservations_by_document: dict[UUID, UploadReservation] = {}
        document_ids = [entry.document_id for entry in entries]
        if document_ids:
            reservations = self._db.scalars(
                select(UploadReservation)
                .join(DurableJob, DurableJob.id == UploadReservation.id)
                .options(selectinload(UploadReservation.job))
                .where(
                    DurableJob.requested_by_id == user_id,
                    DurableJob.project_id.is_(None),
                    DurableJob.document_id.in_(document_ids),
                    DurableJob.status.in_(
                        [
                            JobStatus.PENDING.value,
                            JobStatus.RUNNING.value,
                            JobStatus.FAILED.value,
                        ]
                    ),
                    UploadReservation.superseded_by_id.is_(None),
                )
                .order_by(DurableJob.created_at.desc(), DurableJob.id.desc())
            ).all()
            for reservation in reservations:
                document_id = reservation.job.document_id
                if document_id is not None:
                    reservations_by_document.setdefault(document_id, reservation)

        responses: list[LibraryPaperListEntry] = [
            LibraryPaperListIngestionEntry(
                ingestion=library_ingestion_response(reservation)
            )
            for reservation in visible_standalone_reservations
        ]
        for entry in entries:
            lifecycle_reservation = reservations_by_document.get(entry.document_id)
            if lifecycle_reservation is not None:
                responses.append(
                    LibraryPaperListIngestionEntry(
                        ingestion=library_ingestion_response(lifecycle_reservation)
                    )
                )
            else:
                responses.append(library_paper_list_response(entry))
        positions = [
            LibraryPagePosition(
                key=self._paper_key(entry, sort=sort),
                id=entry.id,
            )
            for entry in entries
        ]
        return LibraryPaperPage(
            items=responses,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
        )

    def paper_count(self, *, user_id: int) -> int:
        return int(
            self._db.scalar(
                select(func.count(LibraryPaper.id)).where(
                    LibraryPaper.user_id == user_id
                )
            )
            or 0
        )

    def ingestion_counts(self, *, user_id: int) -> tuple[int, int]:
        rows = self._db.execute(
            select(DurableJob.status, func.count(DurableJob.id))
            .join(UploadReservation, UploadReservation.id == DurableJob.id)
            .where(
                DurableJob.requested_by_id == user_id,
                DurableJob.project_id.is_(None),
                DurableJob.status.in_(
                    [
                        JobStatus.PENDING.value,
                        JobStatus.RUNNING.value,
                        JobStatus.FAILED.value,
                    ]
                ),
                UploadReservation.superseded_by_id.is_(None),
            )
            .group_by(DurableJob.status)
        ).all()
        by_status = {str(status): int(count) for status, count in rows}
        attention_count = by_status.get(JobStatus.FAILED.value, 0)
        return sum(by_status.values()), attention_count

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse:
        return library_paper_response(
            document_repository.require_library_paper_by_document(
                self._db,
                document_id=document_id,
                user_id=user_id,
            )
        )

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperUpdateResult:
        updated = document_repository.update_library_paper(
            self._db,
            document_id=document_id,
            user_id=user_id,
            request=request,
        )
        return LibraryPaperUpdateResult(
            response=library_paper_response(updated.entry),
            changed=updated.changed,
        )

    def share(self, *, user_id: int, document_id: UUID) -> str:
        return document_repository.rotate_public_share(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )

    def unshare(self, *, user_id: int, document_id: UUID) -> bool:
        return document_repository.revoke_public_share(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )

    def remove(
        self,
        *,
        user_id: int,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> LibraryPaperRemoval:
        document_repository.delete_library_paper(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )
        self._personal_annotations_removed(
            document_id=document_id,
            user_id=user_id,
        )
        scheduled = self._document_removed(
            document_id=document_id,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
        )
        return LibraryPaperRemoval(
            created_gc_job_id=(
                scheduled.job_id
                if scheduled is not None and scheduled.created
                else None
            )
        )

    def remove_many(
        self,
        *,
        user_id: int,
        document_ids: tuple[UUID, ...],
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> dict[UUID, LibraryPaperRemoval]:
        entries = list(
            self._db.scalars(
                select(LibraryPaper)
                .where(
                    LibraryPaper.user_id == user_id,
                    LibraryPaper.document_id.in_(document_ids),
                )
                .with_for_update()
            ).all()
        )
        found = {entry.document_id for entry in entries}
        missing = [
            document_id for document_id in document_ids if document_id not in found
        ]
        if missing:
            from app.shared.domain import AppError, FailureKind

            raise AppError(
                code="library_paper_not_found",
                message="One or more Library papers were not found",
                kind=FailureKind.NOT_FOUND,
            )
        for entry in entries:
            self._personal_annotations_removed(
                document_id=entry.document_id,
                user_id=user_id,
            )
            self._db.delete(entry)
        self._db.flush()
        results: dict[UUID, LibraryPaperRemoval] = {}
        for document_id in document_ids:
            scheduled = self._document_removed(
                document_id=document_id,
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
            results[document_id] = LibraryPaperRemoval(
                created_gc_job_id=(
                    scheduled.job_id
                    if scheduled is not None and scheduled.created
                    else None
                )
            )
        return results

    @staticmethod
    def _paper_key(entry: LibraryPaper, *, sort: LibraryPaperSort) -> str:
        if sort in {LibraryPaperSort.ADDED_ASC, LibraryPaperSort.ADDED_DESC}:
            return entry.created_at.isoformat()
        if sort is LibraryPaperSort.LAST_ACCESSED_DESC:
            return entry.last_accessed_at.isoformat()
        if sort in {
            LibraryPaperSort.PUBLISHED_ASC,
            LibraryPaperSort.PUBLISHED_DESC,
        }:
            fallback = (
                datetime.max if sort is LibraryPaperSort.PUBLISHED_ASC else datetime.min
            )
            return (entry.document.publish_date or fallback).isoformat()
        override_title = entry.metadata_overrides.get("title")
        return str(
            override_title or entry.document.title or entry.document.original_filename
        ).lower()

    def public_share(self, *, share_token: str) -> PublicShare:
        shared = document_repository.require_public_share(
            self._db,
            token=share_token,
        )
        return PublicShare(
            document_id=shared.document.id,
            storage_key=shared.document.s3_object_key,
            document=document_response(shared.document),
            owner=PublicPaperOwnerResponse(
                id=shared.owner.id,
                display_name=shared.owner.display_name or shared.owner.email,
            ),
        )

    def find_entry_id(self, *, user_id: int, document_id: UUID) -> UUID | None:
        return self._db.scalar(
            select(LibraryPaper.id).where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
        )

    def attach(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> LibraryPaperAttachment:
        attached = document_repository.attach_library(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )
        entry = document_repository.require_library_paper_by_document(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )
        return LibraryPaperAttachment(
            library_entry_id=entry.id,
            created=attached.created,
        )
