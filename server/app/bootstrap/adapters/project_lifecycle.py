"""Cross-module transactional Project deletion adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from scholens_job_contracts import require_storage_delete_key
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.database.models import (
    AnnotationComment,
    AnnotationThread,
    Conversation,
    ConversationScopeType,
    Document,
    DurableJob,
    JobStatus,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    ResearchAudienceType,
    ResearchAudioOverview,
    ResearchItem,
)
from app.modules.projects.application.lifecycle import (
    ProjectDeletionPlan,
    ProjectDeletionState,
)
from app.shared.domain import AppError, FailureKind

if TYPE_CHECKING:
    from app.bootstrap.adapters.storage_cleanup import ScheduledStorageDeletion

ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)
PROJECT_DELETION_BATCH_SIZE = 100


class _Digest(Protocol):
    def update(self, data: bytes) -> object: ...


@dataclass(frozen=True, slots=True)
class ProjectDocumentCleanup:
    job_count: int
    created_job_count: int


def _digest_fields(digest: _Digest, *fields: object) -> None:
    for field in fields:
        encoded = ("" if field is None else str(field)).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)


def _section(digest: _Digest, name: str) -> None:
    _digest_fields(digest, name)


def _active_project_job_count(db: Session, *, project_id: UUID) -> int:
    # The Project row is already FOR UPDATE. New FK references cannot appear
    # until this transaction completes, while a scalar count avoids reversing
    # the callback-wide DurableJob -> Project lock order.
    return int(
        db.scalar(
            select(func.count(DurableJob.id)).where(
                DurableJob.project_id == project_id,
                DurableJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )


def inspect_project_deletion(
    db: Session,
    *,
    project: Project,
) -> ProjectDeletionPlan:
    """Return a mutation-free, state-bound Project deletion plan."""
    active_job_count = _active_project_job_count(db, project_id=project.id)
    if active_job_count:
        raise AppError(
            code="project_has_active_jobs",
            message="Wait for active Project jobs to finish before deleting it",
            kind=FailureKind.CONFLICT,
        )

    affected_revision = hashlib.sha256()

    # Lock Documents before their association rows. The already-locked Project
    # prevents the association set from changing while this ordered scan runs.
    for _document_id in db.scalars(
        select(Document.id)
        .join(ProjectPaper, ProjectPaper.document_id == Document.id)
        .where(ProjectPaper.project_id == project.id)
        .order_by(Document.id)
        .with_for_update(of=Document)
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        pass

    _section(affected_revision, "project_papers")
    paper_association_count = 0
    for association_id, document_id in db.execute(
        select(ProjectPaper.id, ProjectPaper.document_id)
        .where(ProjectPaper.project_id == project.id)
        .order_by(ProjectPaper.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        paper_association_count += 1
        _digest_fields(affected_revision, association_id, document_id)

    _section(affected_revision, "research_items")
    research_output_count = 0
    for item_id in db.scalars(
        select(ResearchItem.id)
        .where(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project.id,
        )
        .order_by(ResearchItem.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        research_output_count += 1
        _digest_fields(affected_revision, item_id)

    annotation_revision = hashlib.sha256()
    _section(annotation_revision, "threads")
    annotation_thread_count = 0
    for thread_id, thread_updated_at in db.execute(
        select(AnnotationThread.research_item_id, AnnotationThread.updated_at)
        .join(
            ResearchItem,
            ResearchItem.id == AnnotationThread.research_item_id,
        )
        .where(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project.id,
        )
        .order_by(AnnotationThread.research_item_id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        annotation_thread_count += 1
        for field in (thread_id, thread_updated_at):
            _digest_fields(annotation_revision, field)

    _section(annotation_revision, "comments")
    annotation_comment_count = 0
    for comment_id, creator_id, comment_updated_at in db.execute(
        select(
            AnnotationComment.id,
            AnnotationComment.created_by_id,
            AnnotationComment.updated_at,
        )
        .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
        .where(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project.id,
        )
        .order_by(AnnotationComment.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        annotation_comment_count += 1
        _digest_fields(
            annotation_revision,
            comment_id,
            creator_id,
            comment_updated_at,
        )

    _section(affected_revision, "research_audio")
    storage_object_count = 0
    previous_storage_key: str | None = None
    for audio_item_id, raw_storage_key in db.execute(
        select(
            ResearchAudioOverview.research_item_id,
            ResearchAudioOverview.s3_object_key,
        )
        .join(ResearchItem, ResearchItem.id == ResearchAudioOverview.research_item_id)
        .where(
            ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
            ResearchItem.audience_project_id == project.id,
        )
        .order_by(
            ResearchAudioOverview.s3_object_key,
            ResearchAudioOverview.research_item_id,
        )
        .with_for_update(of=ResearchAudioOverview)
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        storage_key = require_storage_delete_key(raw_storage_key)
        _digest_fields(affected_revision, audio_item_id, storage_key)
        if storage_key != previous_storage_key:
            storage_object_count += 1
            previous_storage_key = storage_key

    _section(affected_revision, "collaborators")
    collaborator_count = 0
    for membership_id, user_id in db.execute(
        select(ProjectCollaborator.id, ProjectCollaborator.user_id)
        .where(ProjectCollaborator.project_id == project.id)
        .order_by(ProjectCollaborator.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        collaborator_count += 1
        _digest_fields(affected_revision, membership_id, user_id)

    _section(affected_revision, "invitations")
    invitation_count = 0
    for invitation_id in db.scalars(
        select(ProjectInvitation.id)
        .where(ProjectInvitation.project_id == project.id)
        .order_by(ProjectInvitation.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        invitation_count += 1
        _digest_fields(affected_revision, invitation_id)

    _section(affected_revision, "conversations")
    conversation_count = 0
    for conversation_id in db.scalars(
        select(Conversation.id)
        .where(
            Conversation.scope_type == ConversationScopeType.PROJECT.value,
            Conversation.project_id == project.id,
        )
        .order_by(Conversation.id)
        .with_for_update()
        .execution_options(yield_per=PROJECT_DELETION_BATCH_SIZE)
    ):
        conversation_count += 1
        _digest_fields(affected_revision, conversation_id)

    return ProjectDeletionPlan(
        state=ProjectDeletionState(
            project_id=project.id,
            owner_id=project.owner_id,
            project_updated_at=project.updated_at,
            paper_association_count=paper_association_count,
            research_output_count=research_output_count,
            annotation_thread_count=annotation_thread_count,
            annotation_comment_count=annotation_comment_count,
            annotation_revision_digest=annotation_revision.hexdigest(),
            collaborator_count=collaborator_count,
            invitation_count=invitation_count,
            conversation_count=conversation_count,
            storage_object_count=storage_object_count,
            active_job_count=active_job_count,
            affected_resource_digest=affected_revision.hexdigest(),
        ),
        project_title=project.title,
    )


def apply_project_deletion(
    db: Session,
    *,
    project: Project,
    plan: ProjectDeletionPlan,
) -> None:
    """Apply the non-cascade semantics from a plan built in this transaction."""
    if plan.state.project_id != project.id:
        raise RuntimeError("project_deletion_plan_mismatch")
    # Conversations are private user history, not Project-owned records. Mark
    # the locked Project contexts deleted before the Project FK becomes NULL.
    db.execute(
        update(Conversation)
        .where(
            Conversation.scope_type == ConversationScopeType.PROJECT.value,
            Conversation.project_id == project.id,
        )
        .values(
            scope_label_snapshot=func.coalesce(
                Conversation.scope_label_snapshot,
                project.title,
            ),
            context_deleted_at=func.now(),
        )
    )


def remove_project_papers_and_schedule_gc(
    db: Session,
    *,
    project_id: UUID,
    origin_operation_id: UUID,
    correlation_id: UUID,
) -> ProjectDocumentCleanup:
    """Remove ProjectPaper rows and schedule GC in bounded locked batches."""
    from app.bootstrap.adapters.document_gc import (
        schedule_document_gc,
    )

    job_count = 0
    created_job_count = 0
    while True:
        rows = tuple(
            db.execute(
                select(ProjectPaper.id, ProjectPaper.document_id)
                .where(ProjectPaper.project_id == project_id)
                .order_by(ProjectPaper.id)
                .limit(PROJECT_DELETION_BATCH_SIZE)
                .with_for_update()
            )
        )
        if not rows:
            break
        association_ids = [association_id for association_id, _document_id in rows]
        document_ids = sorted({document_id for _association_id, document_id in rows})
        db.execute(delete(ProjectPaper).where(ProjectPaper.id.in_(association_ids)))
        db.flush()
        for document_id in document_ids:
            result = schedule_document_gc(
                db,
                document_id=document_id,
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
            if result is None:
                continue
            job_count += 1
            if result.created:
                created_job_count += 1
    return ProjectDocumentCleanup(
        job_count=job_count,
        created_job_count=created_job_count,
    )


def _project_storage_keys(db: Session, *, project_id: UUID) -> Iterator[str]:
    """Yield the Project's unique storage keys in stable keyset order."""

    after_key: str | None = None
    previous_key: str | None = None
    while True:
        statement = (
            select(ResearchAudioOverview.s3_object_key)
            .join(
                ResearchItem,
                ResearchItem.id == ResearchAudioOverview.research_item_id,
            )
            .where(
                ResearchItem.audience_type == ResearchAudienceType.PROJECT.value,
                ResearchItem.audience_project_id == project_id,
            )
            .distinct()
            .order_by(ResearchAudioOverview.s3_object_key)
            .limit(PROJECT_DELETION_BATCH_SIZE)
        )
        if after_key is not None:
            statement = statement.where(ResearchAudioOverview.s3_object_key > after_key)
        page = tuple(db.scalars(statement).all())
        if not page:
            return
        for raw_storage_key in page:
            storage_key = require_storage_delete_key(raw_storage_key)
            after_key = storage_key
            if storage_key == previous_key:
                continue
            if previous_key is not None and storage_key < previous_key:
                raise RuntimeError("project_storage_key_order_invalid")
            yield storage_key
            previous_key = storage_key


def schedule_project_storage_cleanup(
    db: Session,
    *,
    project_id: UUID,
    origin_operation_id: UUID,
    correlation_id: UUID,
) -> ScheduledStorageDeletion | None:
    from app.bootstrap.adapters.storage_cleanup import (
        schedule_storage_deletion,
    )

    return schedule_storage_deletion(
        db,
        object_keys=_project_storage_keys(db, project_id=project_id),
        idempotency_key=f"project:{project_id}",
        origin_operation_id=origin_operation_id,
        correlation_id=correlation_id,
    )
