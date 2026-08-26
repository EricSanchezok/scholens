"""SQLAlchemy/S3 adapters for the personal Library capability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Text, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.database.models import (
    AnnotationComment,
    AnnotationThread,
    DurableJob,
    ResearchItem,
)
from app.helpers.s3 import s3_service
from app.modules.jobs.application.failures import actionable_job_failure
from app.modules.papers.application.contracts.documents import (
    DocumentResponse,
    DocumentMetadataOverrides,
    LibraryPaperIngestionResponse,
    LibraryPaperListEntry,
    LibraryPaperListIngestionEntry,
    LibraryPaperListPaperEntry,
    LibraryPaperResponse,
    LibraryPaperSort,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
)
from app.modules.papers.application.library import (
    LibraryPageDirection,
    LibraryPagePosition,
    LibraryPaperAttachment,
    LibraryPaperConfirmationPlan,
    LibraryPaperConfirmationState,
    LibraryPaperPage,
    LibraryPaperRemoval,
    LibraryPaperRemovalItemState,
    LibraryPaperRemovalPlan,
    LibraryPaperRemovalState,
    LibraryPaperUpdateResult,
    LibraryPaperPageAccess,
    LibraryPaperSummaryPage,
    PublicShare,
)
from app.modules.papers.application.summary_limits import (
    LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
    LIBRARY_PAPER_TEXT_JSON_BYTES,
)
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_CONFIRMATION_COLUMNS,
    DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
)
from app.modules.papers.infrastructure.models import (
    Document,
    LibraryPaper,
    LibraryPaperTag,
    PaperTag,
    UploadReservation,
)
from app.modules.papers.infrastructure.metadata_size import (
    document_json_utf8_upper_bound,
    escaped_json_upper_bound,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.domain import AppError, FailureKind
from app.shared.application.text import json_bounded_prefix
from app.shared.domain.enums import (
    JobStatus,
    PaperStatus,
    ResearchAudienceType,
    ResearchItemKind,
)
from app.shared.infrastructure.sql_patterns import literal_contains_pattern

_LIBRARY_ROW_PIVOT_CURSOR_PREFIX = "\x00library-row-v1:"
_LIBRARY_OVERRIDE_DATE_CHARACTERS = 64


@dataclass(frozen=True, slots=True)
class _LibraryPaperListPlan:
    paper_position: LibraryPagePosition | None
    count_filters: tuple[Any, ...]
    page_filters: tuple[Any, ...]
    order: Any
    id_order: Any


def _library_row_pivot_cursor_key(item_id: UUID) -> str:
    return f"{_LIBRARY_ROW_PIVOT_CURSOR_PREFIX}{item_id}"


def _bounded_optional_row_text(value: str | None, *, max_bytes: int) -> str | None:
    return (
        json_bounded_prefix(value, max_bytes=max_bytes) if value is not None else None
    )


def _bounded_override_datetime(value: str | None) -> tuple[datetime | None, bool]:
    if value is None:
        return None, False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")), False
    except ValueError:
        return None, True


def _library_paper_summary_statement() -> Any:
    """Select one bounded scalar representation without ORM hydration."""

    tag_exists = exists(
        select(LibraryPaperTag.library_paper_id).where(
            LibraryPaperTag.library_paper_id == LibraryPaper.id
        )
    )
    override_title = LibraryPaper.metadata_overrides["title"].astext
    override_abstract = LibraryPaper.metadata_overrides["abstract"].astext
    override_doi = LibraryPaper.metadata_overrides["doi"].astext
    override_journal = LibraryPaper.metadata_overrides["journal"].astext
    override_publisher = LibraryPaper.metadata_overrides["publisher"].astext
    override_publish_date = LibraryPaper.metadata_overrides["publish_date"].astext
    content_truncated = or_(
        func.char_length(Document.original_filename) > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.char_length(Document.mime_type) > LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.title, Text)), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.abstract, Text)), 0)
        > LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.doi, Text)), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.journal, Text)), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.publisher, Text)), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.summary, Text)), 0)
        > LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(cast(Document.parser_quality, Text)), 0)
        > LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        func.coalesce(
            func.char_length(cast(Document.parser_warning_code, Text)),
            0,
        )
        > LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        func.coalesce(func.char_length(override_title), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(override_abstract), 0)
        > LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(override_doi), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(override_journal), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(override_publisher), 0)
        > LIBRARY_PAPER_TEXT_JSON_BYTES,
        func.coalesce(func.char_length(override_publish_date), 0)
        > _LIBRARY_OVERRIDE_DATE_CHARACTERS,
        LibraryPaper.metadata_overrides.op("?")("authors"),
        LibraryPaper.metadata_overrides.op("?")("institutions"),
        Document.authors.is_not(None),
        Document.institutions.is_not(None),
        Document.keywords.is_not(None),
        Document.summary_citations.is_not(None),
        Document.starter_questions.is_not(None),
        Document.preview_s3_key.is_not(None),
        tag_exists,
    )
    return select(
        LibraryPaper.id.label("library_entry_id"),
        LibraryPaper.user_id,
        LibraryPaper.status,
        LibraryPaper.last_accessed_at,
        func.left(override_title, LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "override_title"
        ),
        func.left(override_abstract, LIBRARY_PAPER_LONG_TEXT_JSON_BYTES).label(
            "override_abstract"
        ),
        func.left(override_doi, LIBRARY_PAPER_TEXT_JSON_BYTES).label("override_doi"),
        func.left(override_journal, LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "override_journal"
        ),
        func.left(override_publisher, LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "override_publisher"
        ),
        func.left(
            override_publish_date,
            _LIBRARY_OVERRIDE_DATE_CHARACTERS,
        ).label("override_publish_date"),
        LibraryPaper.is_public,
        LibraryPaper.created_at.label("entry_created_at"),
        LibraryPaper.updated_at.label("entry_updated_at"),
        Document.id.label("document_id"),
        func.left(Document.original_filename, LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "original_filename"
        ),
        func.left(Document.mime_type, LIBRARY_PAPER_LIST_VALUE_JSON_BYTES).label(
            "mime_type"
        ),
        Document.size_bytes,
        func.left(cast(Document.title, Text), LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "title"
        ),
        func.left(
            cast(Document.abstract, Text),
            LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        ).label("abstract"),
        func.left(cast(Document.doi, Text), LIBRARY_PAPER_TEXT_JSON_BYTES).label("doi"),
        func.left(cast(Document.journal, Text), LIBRARY_PAPER_TEXT_JSON_BYTES).label(
            "journal"
        ),
        func.left(
            cast(Document.publisher, Text),
            LIBRARY_PAPER_TEXT_JSON_BYTES,
        ).label("publisher"),
        Document.publish_date,
        func.left(
            cast(Document.summary, Text),
            LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        ).label("summary"),
        Document.processing_status,
        func.left(
            cast(Document.parser_quality, Text),
            LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        ).label("parser_quality"),
        func.left(
            cast(Document.parser_warning_code, Text),
            LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        ).label("parser_warning_code"),
        Document.created_at.label("document_created_at"),
        Document.updated_at.label("document_updated_at"),
        content_truncated.label("content_truncated"),
    ).join(Document, Document.id == LibraryPaper.document_id)


def _library_paper_summary_response(row: Any) -> tuple[LibraryPaperResponse, bool]:
    override_publish_date, invalid_override_publish_date = _bounded_override_datetime(
        row.override_publish_date
    )
    original_filename = json_bounded_prefix(
        row.original_filename,
        max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
    )
    mime_type = json_bounded_prefix(
        row.mime_type,
        max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
    )
    bounded = {
        "override_title": _bounded_optional_row_text(
            row.override_title,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "override_abstract": _bounded_optional_row_text(
            row.override_abstract,
            max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        ),
        "override_doi": _bounded_optional_row_text(
            row.override_doi,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "override_journal": _bounded_optional_row_text(
            row.override_journal,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "override_publisher": _bounded_optional_row_text(
            row.override_publisher,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "title": _bounded_optional_row_text(
            row.title,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "abstract": _bounded_optional_row_text(
            row.abstract,
            max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        ),
        "doi": _bounded_optional_row_text(
            row.doi,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "journal": _bounded_optional_row_text(
            row.journal,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "publisher": _bounded_optional_row_text(
            row.publisher,
            max_bytes=LIBRARY_PAPER_TEXT_JSON_BYTES,
        ),
        "summary": _bounded_optional_row_text(
            row.summary,
            max_bytes=LIBRARY_PAPER_LONG_TEXT_JSON_BYTES,
        ),
        "parser_quality": _bounded_optional_row_text(
            row.parser_quality,
            max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        ),
        "parser_warning_code": _bounded_optional_row_text(
            row.parser_warning_code,
            max_bytes=LIBRARY_PAPER_LIST_VALUE_JSON_BYTES,
        ),
    }
    source_values = {key: getattr(row, key) for key in bounded if hasattr(row, key)}
    truncated = (
        bool(row.content_truncated)
        or original_filename != row.original_filename
        or mime_type != row.mime_type
        or invalid_override_publish_date
        or any(bounded[key] != value for key, value in source_values.items())
    )
    return (
        LibraryPaperResponse(
            library_entry_id=row.library_entry_id,
            user_id=row.user_id,
            status=row.status,
            last_accessed_at=row.last_accessed_at,
            metadata_overrides=DocumentMetadataOverrides(
                title=bounded["override_title"],
                authors=None,
                abstract=bounded["override_abstract"],
                institutions=None,
                doi=bounded["override_doi"],
                journal=bounded["override_journal"],
                publisher=bounded["override_publisher"],
                publish_date=override_publish_date,
            ),
            is_public=row.is_public,
            preview_url=None,
            tags=[],
            document=DocumentResponse(
                document_id=row.document_id,
                original_filename=original_filename,
                mime_type=mime_type,
                size_bytes=row.size_bytes,
                title=bounded["title"],
                authors=None,
                abstract=bounded["abstract"],
                institutions=None,
                keywords=None,
                doi=bounded["doi"],
                journal=bounded["journal"],
                publisher=bounded["publisher"],
                publish_date=row.publish_date,
                summary=bounded["summary"],
                summary_citations=None,
                starter_questions=None,
                processing_status=row.processing_status,
                parser_quality=bounded["parser_quality"],
                parser_warning_code=bounded["parser_warning_code"],
                created_at=row.document_created_at,
                updated_at=row.document_updated_at,
            ),
            created_at=row.entry_created_at,
            updated_at=row.entry_updated_at,
        ),
        truncated,
    )


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


def _confirmation_state(entry: LibraryPaper) -> LibraryPaperConfirmationState:
    return LibraryPaperConfirmationState(
        library_entry_id=entry.id,
        document_id=entry.document_id,
        document_sha256=entry.document.sha256,
        display_title=entry.document.title or entry.document.original_filename,
        is_public=entry.is_public,
        share_token_hash=entry.share_token_hash,
    )


class _Digest(Protocol):
    def update(self, value: bytes) -> object: ...

    def hexdigest(self) -> str: ...


def _update_annotation_digest(
    digest: _Digest,
    record_kind: str,
    *values: str,
) -> None:
    """Append one unambiguous, bounded record to a rolling confirmation digest."""
    for value in (record_kind, *values):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)


def _new_annotation_digest() -> _Digest:
    digest = hashlib.sha256()
    _update_annotation_digest(digest, "version", "library-removal-annotations-v2")
    return digest


def _library_ingestion_response(
    *,
    job_id: UUID,
    display_name: str,
    source_kind: str,
    status: str,
    progress_code: str | None,
    project_id: UUID | None,
    document_id: UUID | None,
    error_code: str | None,
    created_at: datetime,
) -> LibraryPaperIngestionResponse:
    stages = {
        "downloading",
        "parsing",
        "extracting_metadata",
        "indexing",
        "finalizing",
    }
    if status == JobStatus.RUNNING.value:
        state = "processing"
        stage = progress_code if progress_code in stages else "parsing"
    elif status == JobStatus.FAILED.value:
        state = "failed"
        stage = progress_code if progress_code in stages else "queued"
    else:
        state, stage = "queued", "queued"
    return LibraryPaperIngestionResponse.model_validate(
        {
            "id": job_id,
            "display_name": display_name,
            "source_kind": source_kind,
            "state": state,
            "stage": stage,
            "project_id": project_id,
            "document_id": document_id,
            "failure": actionable_job_failure(error_code),
            "created_at": created_at,
        }
    )


def library_ingestion_response(
    reservation: UploadReservation,
) -> LibraryPaperIngestionResponse:
    job = reservation.job
    return _library_ingestion_response(
        job_id=job.id,
        display_name=reservation.display_name,
        source_kind=reservation.source_kind,
        status=job.status,
        progress_code=job.progress_code,
        project_id=job.project_id,
        document_id=job.document_id,
        error_code=job.error_code,
        created_at=job.created_at,
    )


def _library_tag_json_upper_bound() -> Any:
    return (
        select(
            func.coalesce(
                func.sum(
                    escaped_json_upper_bound(PaperTag.name)
                    + escaped_json_upper_bound(PaperTag.color)
                    + 128
                ),
                0,
            )
        )
        .select_from(LibraryPaperTag)
        .join(PaperTag, PaperTag.id == LibraryPaperTag.tag_id)
        .where(LibraryPaperTag.library_paper_id == LibraryPaper.id)
        .correlate(LibraryPaper)
        .scalar_subquery()
    )


def _library_paper_json_upper_bound() -> Any:
    return (
        document_json_utf8_upper_bound()
        + escaped_json_upper_bound(LibraryPaper.metadata_overrides)
        + _library_tag_json_upper_bound()
        + 4_096
    )


def _library_paper_list_plan(
    *,
    user_id: int,
    query: str | None,
    tag_ids: tuple[UUID, ...],
    statuses: tuple[PaperStatus, ...],
    sort: LibraryPaperSort,
    direction: LibraryPageDirection,
    position: LibraryPagePosition | None,
) -> _LibraryPaperListPlan:
    paper_position = (
        position if position is not None and position.kind == "paper" else None
    )
    title = func.lower(
        func.coalesce(
            LibraryPaper.metadata_overrides["title"].astext,
            Document.title,
            Document.original_filename,
        )
    )
    key: Any
    if sort in {LibraryPaperSort.ADDED_ASC, LibraryPaperSort.ADDED_DESC}:
        key = LibraryPaper.created_at
        cursor_key: object | None = (
            datetime.fromisoformat(paper_position.key)
            if paper_position is not None
            else None
        )
        natural_ascending = sort is LibraryPaperSort.ADDED_ASC
    elif sort is LibraryPaperSort.LAST_ACCESSED_DESC:
        key = LibraryPaper.last_accessed_at
        cursor_key = (
            datetime.fromisoformat(paper_position.key)
            if paper_position is not None
            else None
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
            datetime.fromisoformat(paper_position.key)
            if paper_position is not None
            else None
        )
        natural_ascending = sort is LibraryPaperSort.PUBLISHED_ASC
    else:
        key = title
        if (
            paper_position is not None
            and paper_position.key == _library_row_pivot_cursor_key(paper_position.id)
        ):
            pivot_entry = aliased(LibraryPaper)
            pivot_document = aliased(Document)
            cursor_key = (
                select(
                    func.lower(
                        func.coalesce(
                            pivot_entry.metadata_overrides["title"].astext,
                            pivot_document.title,
                            pivot_document.original_filename,
                        )
                    )
                )
                .join(
                    pivot_document,
                    pivot_document.id == pivot_entry.document_id,
                )
                .where(pivot_entry.id == paper_position.id)
                .scalar_subquery()
            )
        else:
            cursor_key = paper_position.key if paper_position is not None else None
        natural_ascending = True

    count_filters: list[Any] = [LibraryPaper.user_id == user_id]
    if query is not None:
        pattern = literal_contains_pattern(query.lower())
        count_filters.append(
            or_(
                title.like(pattern, escape="\\"),
                func.lower(func.coalesce(Document.abstract, "")).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(func.coalesce(Document.doi, "")).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(func.array_to_string(Document.authors, " ")).like(
                    pattern,
                    escape="\\",
                ),
            )
        )
    if tag_ids:
        count_filters.append(
            LibraryPaper.id.in_(
                select(LibraryPaperTag.library_paper_id).where(
                    LibraryPaperTag.tag_id.in_(tag_ids)
                )
            )
        )
    if statuses:
        count_filters.append(
            LibraryPaper.status.in_([status.value for status in statuses])
        )

    effective_ascending = (
        natural_ascending
        if direction is LibraryPageDirection.FORWARD
        else not natural_ascending
    )
    page_filters = list(count_filters)
    if paper_position is not None and cursor_key is not None:
        if effective_ascending:
            page_filters.append(
                or_(
                    key > cursor_key,
                    and_(key == cursor_key, LibraryPaper.id > paper_position.id),
                )
            )
        else:
            page_filters.append(
                or_(
                    key < cursor_key,
                    and_(key == cursor_key, LibraryPaper.id < paper_position.id),
                )
            )
    return _LibraryPaperListPlan(
        paper_position=paper_position,
        count_filters=tuple(count_filters),
        page_filters=tuple(page_filters),
        order=key.asc() if effective_ascending else key.desc(),
        id_order=(
            LibraryPaper.id.asc() if effective_ascending else LibraryPaper.id.desc()
        ),
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
        include_active_ingestions: bool = True,
        maximum_retained_bytes: int | None = None,
    ) -> LibraryPaperPage:
        plan = _library_paper_list_plan(
            user_id=user_id,
            query=query,
            tag_ids=tag_ids,
            statuses=statuses,
            sort=sort,
            direction=direction,
            position=position,
        )
        paper_position = plan.paper_position

        active_reservation_count = 0
        active_has_more = False
        visible_standalone_reservations: list[
            tuple[LibraryPaperIngestionResponse, LibraryPagePosition]
        ] = []
        if include_active_ingestions and not tag_ids and not statuses:
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
                UploadReservation.dismissed_at.is_(None),
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
                pattern = literal_contains_pattern(query.lower())
                reservation_filters.append(
                    func.lower(UploadReservation.display_name).like(
                        pattern, escape="\\"
                    )
                )
            active_reservation_count = int(
                self._db.scalar(
                    select(func.count(UploadReservation.id))
                    .join(DurableJob, DurableJob.id == UploadReservation.id)
                    .where(*reservation_filters)
                )
                or 0
            )
            page_reservations = (
                position is None
                or position.kind == "ingestion"
                or (
                    direction is LibraryPageDirection.BACKWARD
                    and position.kind == "paper"
                )
            )
            if page_reservations:
                paged_reservation_filters = list(reservation_filters)
                if position is not None and position.kind == "ingestion":
                    position_created_at = datetime.fromisoformat(position.key)
                    if direction is LibraryPageDirection.FORWARD:
                        paged_reservation_filters.append(
                            or_(
                                DurableJob.created_at < position_created_at,
                                and_(
                                    DurableJob.created_at == position_created_at,
                                    DurableJob.id < position.id,
                                ),
                            )
                        )
                    else:
                        paged_reservation_filters.append(
                            or_(
                                DurableJob.created_at > position_created_at,
                                and_(
                                    DurableJob.created_at == position_created_at,
                                    DurableJob.id > position.id,
                                ),
                            )
                        )
                reservation_order = (
                    (DurableJob.created_at.desc(), DurableJob.id.desc())
                    if direction is LibraryPageDirection.FORWARD
                    else (DurableJob.created_at.asc(), DurableJob.id.asc())
                )
                reservation_rows = list(
                    self._db.execute(
                        select(
                            DurableJob.id.label("job_id"),
                            UploadReservation.display_name,
                            UploadReservation.source_kind,
                            DurableJob.status,
                            DurableJob.progress_code,
                            DurableJob.project_id,
                            DurableJob.document_id,
                            DurableJob.error_code,
                            DurableJob.created_at,
                        )
                        .join(DurableJob, DurableJob.id == UploadReservation.id)
                        .where(*paged_reservation_filters)
                        .order_by(*reservation_order)
                        .limit(limit + 1)
                    ).all()
                )
                active_has_more = len(reservation_rows) > limit
                reservation_rows = reservation_rows[:limit]
                if direction is LibraryPageDirection.BACKWARD:
                    reservation_rows.reverse()
                visible_standalone_reservations = [
                    (
                        _library_ingestion_response(
                            job_id=row.job_id,
                            display_name=row.display_name,
                            source_kind=row.source_kind,
                            status=row.status,
                            progress_code=row.progress_code,
                            project_id=row.project_id,
                            document_id=row.document_id,
                            error_code=row.error_code,
                            created_at=row.created_at,
                        ),
                        LibraryPagePosition(
                            key=row.created_at.isoformat(),
                            id=row.job_id,
                            kind="ingestion",
                        ),
                    )
                    for row in reservation_rows
                ]

        count_statement = (
            select(func.count(LibraryPaper.id))
            .join(Document, Document.id == LibraryPaper.document_id)
            .where(*plan.count_filters)
        )
        paper_count = int(self._db.scalar(count_statement) or 0)
        total_count = paper_count + active_reservation_count
        if paper_position is not None:
            paper_limit = limit
        elif direction is LibraryPageDirection.FORWARD and not active_has_more:
            paper_limit = max(0, limit - len(visible_standalone_reservations))
        else:
            paper_limit = 0
        entries: list[LibraryPaper] = []
        paper_has_more = False
        if paper_limit > 0:
            ordered_ids = list(
                self._db.scalars(
                    select(LibraryPaper.id)
                    .join(Document, Document.id == LibraryPaper.document_id)
                    .where(*plan.page_filters)
                    .order_by(plan.order, plan.id_order)
                    .limit(paper_limit + 1)
                ).all()
            )
            paper_has_more = len(ordered_ids) > paper_limit
            page_ids = ordered_ids[:paper_limit]
            if maximum_retained_bytes is not None:
                paper_upper_bounds = self._db.scalars(
                    select(
                        _library_paper_json_upper_bound().label(
                            "durable_json_utf8_upper_bound"
                        )
                    )
                    .select_from(LibraryPaper)
                    .join(Document, Document.id == LibraryPaper.document_id)
                    .where(LibraryPaper.id.in_(page_ids))
                ).all()
                ingestion_upper_bound = sum(
                    len(ingestion.model_dump_json().encode("utf-8")) + 128
                    for ingestion, _position in visible_standalone_reservations
                )
                durable_upper_bound = ingestion_upper_bound + sum(
                    int(value) for value in paper_upper_bounds
                )
                if durable_upper_bound > maximum_retained_bytes:
                    raise AppError(
                        code="tool_result_budget_exceeded",
                        message="The tool result exceeds its safe output budget",
                        kind=FailureKind.INTERNAL,
                        details={
                            "tool": "list_library_papers",
                            "max_output_bytes": 200 * 1024,
                            "durable_json_utf8_upper_bound": durable_upper_bound,
                            "replacement_tool": "list_library_paper_summaries",
                        },
                    )
            if page_ids:
                hydrated = self._db.scalars(
                    select(LibraryPaper)
                    .options(
                        selectinload(LibraryPaper.document).load_only(
                            *DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
                            raiseload=True,
                        ),
                        selectinload(LibraryPaper.tags),
                    )
                    .where(LibraryPaper.id.in_(page_ids))
                ).all()
                entries_by_id = {entry.id: entry for entry in hydrated}
                entries = [
                    entry
                    for entry_id in page_ids
                    if (entry := entries_by_id.get(entry_id)) is not None
                ]
            if direction is LibraryPageDirection.BACKWARD:
                entries.reverse()

        if direction is LibraryPageDirection.BACKWARD and paper_position is not None:
            # Active standalone ingestions form the leading segment of the
            # combined Library collection. Once reverse paper paging reaches
            # that seam, prepend the oldest active rows so next->previous is
            # lossless even when a page contains both entry kinds.
            reservation_slots = max(0, limit - len(entries))
            visible_standalone_reservations = (
                visible_standalone_reservations[-reservation_slots:]
                if reservation_slots
                else []
            )
            active_has_more = active_reservation_count > len(
                visible_standalone_reservations
            )
        has_more = (
            active_has_more
            or paper_has_more
            or (
                direction is LibraryPageDirection.FORWARD
                and paper_position is None
                and paper_limit == 0
                and paper_count > 0
            )
        )
        reservations_by_document: dict[UUID, UploadReservation] = {}
        document_ids = [entry.document_id for entry in entries]
        if include_active_ingestions and document_ids:
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
                    UploadReservation.dismissed_at.is_(None),
                )
                .order_by(DurableJob.created_at.desc(), DurableJob.id.desc())
            ).all()
            for reservation in reservations:
                document_id = reservation.job.document_id
                if document_id is not None:
                    reservations_by_document.setdefault(document_id, reservation)

        responses: list[LibraryPaperListEntry] = [
            LibraryPaperListIngestionEntry(ingestion=ingestion)
            for ingestion, _position in visible_standalone_reservations
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
            position for _ingestion, position in visible_standalone_reservations
        ] + [
            LibraryPagePosition(
                key=self._paper_key(entry, sort=sort),
                id=entry.id,
                kind="paper",
            )
            for entry in entries
        ]
        return LibraryPaperPage(
            items=responses,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
        )

    def list_summaries(
        self,
        *,
        user_id: int,
        query: str | None,
        tag_ids: tuple[UUID, ...],
        statuses: tuple[PaperStatus, ...],
        sort: LibraryPaperSort,
        limit: int,
        direction: LibraryPageDirection,
        position: LibraryPagePosition | None,
    ) -> LibraryPaperSummaryPage:
        plan = _library_paper_list_plan(
            user_id=user_id,
            query=query,
            tag_ids=tag_ids,
            statuses=statuses,
            sort=sort,
            direction=direction,
            position=position,
        )
        total_count = int(
            self._db.scalar(
                select(func.count(LibraryPaper.id))
                .join(Document, Document.id == LibraryPaper.document_id)
                .where(*plan.count_filters)
            )
            or 0
        )
        rows = list(
            self._db.execute(
                _library_paper_summary_statement()
                .where(*plan.page_filters)
                .order_by(plan.order, plan.id_order)
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction is LibraryPageDirection.BACKWARD:
            rows.reverse()
        items: list[LibraryPaperListEntry] = []
        positions: list[LibraryPagePosition] = []
        truncated = False
        for row in rows:
            response, row_truncated = _library_paper_summary_response(row)
            truncated = truncated or row_truncated
            items.append(
                LibraryPaperListPaperEntry(
                    **response.model_dump(),
                )
            )
            if sort in {LibraryPaperSort.ADDED_ASC, LibraryPaperSort.ADDED_DESC}:
                position_key = row.entry_created_at.isoformat()
            elif sort is LibraryPaperSort.LAST_ACCESSED_DESC:
                position_key = row.last_accessed_at.isoformat()
            elif sort in {
                LibraryPaperSort.PUBLISHED_ASC,
                LibraryPaperSort.PUBLISHED_DESC,
            }:
                sentinel = (
                    datetime.max
                    if sort is LibraryPaperSort.PUBLISHED_ASC
                    else datetime.min
                )
                position_key = (row.publish_date or sentinel).isoformat()
            else:
                position_key = _library_row_pivot_cursor_key(row.library_entry_id)
            positions.append(
                LibraryPagePosition(
                    key=position_key,
                    id=row.library_entry_id,
                    kind="paper",
                )
            )
        return LibraryPaperSummaryPage(
            items=items,
            positions=positions,
            has_more=has_more,
            total_count=total_count,
            content_truncated=truncated,
        )

    def _summary_by_document(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> tuple[LibraryPaperResponse, bool]:
        row = self._db.execute(
            _library_paper_summary_statement().where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
        ).one_or_none()
        if row is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return _library_paper_summary_response(row)

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
                UploadReservation.dismissed_at.is_(None),
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

    def get_revision(
        self, *, user_id: int, document_id: UUID
    ) -> LibraryPaperPageAccess:
        return self._library_paper_page_access(
            user_id=user_id,
            document_id=document_id,
            include_size=False,
        )

    def get_retained_size(
        self, *, user_id: int, document_id: UUID
    ) -> LibraryPaperPageAccess:
        return self._library_paper_page_access(
            user_id=user_id,
            document_id=document_id,
            include_size=True,
        )

    def _library_paper_page_access(
        self,
        *,
        user_id: int,
        document_id: UUID,
        include_size: bool,
    ) -> LibraryPaperPageAccess:
        tag_digest = (
            select(
                func.md5(
                    func.coalesce(
                        cast(
                            func.jsonb_object_agg(
                                cast(PaperTag.id, Text),
                                func.jsonb_build_array(
                                    PaperTag.name,
                                    PaperTag.color,
                                ),
                            ),
                            Text,
                        ),
                        "{}",
                    )
                )
            )
            .select_from(LibraryPaperTag)
            .join(PaperTag, PaperTag.id == LibraryPaperTag.tag_id)
            .where(LibraryPaperTag.library_paper_id == LibraryPaper.id)
            .correlate(LibraryPaper)
            .scalar_subquery()
        )
        columns: list[Any] = [
            LibraryPaper.id.label("library_entry_id"),
            LibraryPaper.document_id,
            LibraryPaper.updated_at.label("entry_updated_at"),
            Document.updated_at.label("document_updated_at"),
            Document.preview_s3_key,
            tag_digest.label("tag_digest"),
        ]
        if include_size:
            columns.append(
                _library_paper_json_upper_bound().label("durable_json_utf8_upper_bound")
            )
        row = self._db.execute(
            select(*columns)
            .join(Document, Document.id == LibraryPaper.document_id)
            .where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
        ).one_or_none()
        if row is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        revision = hashlib.sha256(
            "|".join(
                (
                    row.entry_updated_at.isoformat(),
                    row.document_updated_at.isoformat(),
                    str(row.tag_digest),
                )
            ).encode()
        ).hexdigest()
        return LibraryPaperPageAccess(
            library_entry_id=row.library_entry_id,
            document_id=row.document_id,
            revision=revision,
            access_url=(
                s3_service.generate_presigned_url(row.preview_s3_key)
                if row.preview_s3_key
                else None
            ),
            durable_json_utf8_upper_bound=(
                int(row.durable_json_utf8_upper_bound) if include_size else None
            ),
        )

    def confirmation_plan(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> LibraryPaperConfirmationPlan:
        entry = self._db.scalar(
            select(LibraryPaper)
            .where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
            .options(
                selectinload(LibraryPaper.document).load_only(
                    *DOCUMENT_CONFIRMATION_COLUMNS,
                    raiseload=True,
                )
            )
            .with_for_update()
        )
        if entry is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return LibraryPaperConfirmationPlan(state=_confirmation_state(entry))

    def _lock_removal_entries(
        self,
        *,
        user_id: int,
        document_ids: tuple[UUID, ...],
        load_confirmation_document: bool,
    ) -> dict[UUID, LibraryPaper]:
        """Lock one removal batch in the repository-wide dependency order.

        Document is the synchronization root for annotation and garbage-
        collection writes. Locking it before LibraryPaper prevents the old
        LibraryPaper -> Document inversion from deadlocking concurrent removal
        and GC paths.
        """
        unique_document_ids = tuple(dict.fromkeys(document_ids))
        locked_document_ids = tuple(
            self._db.scalars(
                select(Document.id)
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    LibraryPaper.user_id == user_id,
                    Document.id.in_(unique_document_ids),
                )
                .order_by(Document.id)
                .with_for_update(of=Document)
            ).all()
        )
        if set(locked_document_ids) != set(unique_document_ids):
            raise AppError(
                code="library_paper_not_found",
                message="One or more Library papers were not found",
                kind=FailureKind.NOT_FOUND,
            )

        statement = (
            select(LibraryPaper)
            .where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id.in_(unique_document_ids),
            )
            .order_by(LibraryPaper.id)
            .with_for_update(of=LibraryPaper)
        )
        if load_confirmation_document:
            statement = statement.options(
                selectinload(LibraryPaper.document).load_only(
                    *DOCUMENT_CONFIRMATION_COLUMNS,
                    raiseload=True,
                )
            )
        entries = tuple(self._db.scalars(statement).all())
        entries_by_document = {entry.document_id: entry for entry in entries}
        if set(entries_by_document) != set(unique_document_ids):
            raise AppError(
                code="library_paper_not_found",
                message="One or more Library papers were not found",
                kind=FailureKind.NOT_FOUND,
            )
        return entries_by_document

    def removal_plan(
        self,
        *,
        user_id: int,
        document_ids: tuple[UUID, ...],
    ) -> LibraryPaperRemovalPlan:
        unique_document_ids = tuple(dict.fromkeys(document_ids))
        entries_by_document = self._lock_removal_entries(
            user_id=user_id,
            document_ids=unique_document_ids,
            load_confirmation_document=True,
        )
        digests = {
            document_id: _new_annotation_digest() for document_id in unique_document_ids
        }
        thread_counts = dict.fromkeys(unique_document_ids, 0)
        comment_counts = dict.fromkeys(unique_document_ids, 0)

        annotation_filter = (
            ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
            ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value,
            ResearchItem.created_by_id == user_id,
            ResearchItem.target_document_id.in_(unique_document_ids),
        )
        item_rows = self._db.execute(
            select(
                ResearchItem.target_document_id,
                ResearchItem.id,
                ResearchItem.updated_at,
            )
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .where(*annotation_filter)
            .order_by(ResearchItem.target_document_id, ResearchItem.id)
            .with_for_update(of=ResearchItem)
            .execution_options(yield_per=100)
        ).tuples()
        for target_document_id, thread_id, item_updated_at in item_rows:
            if target_document_id is None:
                raise RuntimeError("personal_annotation_target_missing")
            thread_counts[target_document_id] += 1
            _update_annotation_digest(
                digests[target_document_id],
                "item",
                str(thread_id),
                item_updated_at.isoformat(),
            )

        thread_rows = self._db.execute(
            select(
                ResearchItem.target_document_id,
                AnnotationThread.research_item_id,
                AnnotationThread.updated_at,
            )
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == ResearchItem.id,
            )
            .where(*annotation_filter)
            .order_by(
                ResearchItem.target_document_id,
                AnnotationThread.research_item_id,
            )
            .with_for_update(of=AnnotationThread)
            .execution_options(yield_per=100)
        ).tuples()
        for target_document_id, thread_id, thread_updated_at in thread_rows:
            if target_document_id is None:
                raise RuntimeError("personal_annotation_target_missing")
            _update_annotation_digest(
                digests[target_document_id],
                "thread",
                str(thread_id),
                thread_updated_at.isoformat(),
            )

        comment_rows = self._db.execute(
            select(
                ResearchItem.target_document_id,
                AnnotationComment.thread_id,
                AnnotationComment.id,
                AnnotationComment.updated_at,
            )
            .select_from(AnnotationComment)
            .join(
                AnnotationThread,
                AnnotationThread.research_item_id == AnnotationComment.thread_id,
            )
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationThread.research_item_id,
            )
            .where(*annotation_filter)
            .order_by(
                ResearchItem.target_document_id,
                AnnotationComment.thread_id,
                AnnotationComment.id,
            )
            .with_for_update(of=AnnotationComment)
            .execution_options(yield_per=100)
        ).tuples()
        for (
            target_document_id,
            thread_id,
            comment_id,
            comment_updated_at,
        ) in comment_rows:
            if target_document_id is None:
                raise RuntimeError("personal_annotation_target_missing")
            comment_counts[target_document_id] += 1
            _update_annotation_digest(
                digests[target_document_id],
                "comment",
                str(thread_id),
                str(comment_id),
                comment_updated_at.isoformat(),
            )

        items: list[LibraryPaperRemovalItemState] = []
        for document_id in unique_document_ids:
            base = _confirmation_state(entries_by_document[document_id])
            items.append(
                LibraryPaperRemovalItemState(
                    **base.model_dump(),
                    personal_annotation_thread_count=thread_counts[document_id],
                    personal_annotation_comment_count=comment_counts[document_id],
                    personal_annotation_digest=digests[document_id].hexdigest(),
                )
            )
        return LibraryPaperRemovalPlan(
            state=LibraryPaperRemovalState(items=tuple(items))
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
            response=self.get(user_id=user_id, document_id=updated.document_id),
            changed=updated.changed,
        )

    def update_summary(
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
        response, content_truncated = self._summary_by_document(
            user_id=user_id,
            document_id=updated.document_id,
        )
        return LibraryPaperUpdateResult(
            response=response,
            changed=updated.changed,
            content_truncated=content_truncated,
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
        entry = self._lock_removal_entries(
            user_id=user_id,
            document_ids=(document_id,),
            load_confirmation_document=False,
        )[document_id]
        self._personal_annotations_removed(
            document_id=document_id,
            user_id=user_id,
        )
        self._db.delete(entry)
        self._db.flush()
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
        unique_document_ids = tuple(dict.fromkeys(document_ids))
        entries_by_document = self._lock_removal_entries(
            user_id=user_id,
            document_ids=unique_document_ids,
            load_confirmation_document=False,
        )
        for entry in entries_by_document.values():
            self._personal_annotations_removed(
                document_id=entry.document_id,
                user_id=user_id,
            )
            self._db.delete(entry)
        self._db.flush()
        results: dict[UUID, LibraryPaperRemoval] = {}
        for document_id in unique_document_ids:
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

    def resolve_public_document_id(self, *, share_token: str) -> UUID:
        return document_repository.require_public_share_document_id(
            self._db,
            token=share_token,
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
        entry_id = self.find_entry_id(
            user_id=user_id,
            document_id=document_id,
        )
        if entry_id is None:
            raise RuntimeError("attached_library_paper_not_found")
        return LibraryPaperAttachment(
            library_entry_id=entry_id,
            created=attached.created,
        )
