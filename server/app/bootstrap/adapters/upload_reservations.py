"""Cross-module upload authorization and owner-paid resource reservation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.modules.billing.infrastructure.account_locks import (
    lock_account_resource_quota,
)
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    UploadReservation,
    Project,
    ProjectPaper,
)
from app.shared.domain import AppError, FailureKind
from app.modules.billing.domain import (
    KB_SIZE_KEY,
    PAPER_UPLOAD_KEY,
    PROJECTS_KEY,
    PROJECT_PAPERS_KEY,
)
from app.modules.billing.infrastructure.quotas import (
    get_quota_user,
    get_user_entitlements,
)
from app.modules.projects.infrastructure.access import (
    require_project_permission_for_update,
)
from app.modules.projects.application.lifecycle import (
    ProjectQuotaOwnerState,
    ProjectQuotaTransferPlan,
    ProjectQuotaTransferState,
    ProjectReservationAssignment,
)
from app.modules.papers.application.upload_intent import resolve_add_to_library
from app.shared.application import Actor
from app.modules.jobs.infrastructure.repository import CreateJob, job_repository
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

ACTIVE_UPLOAD_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class UploadReservationResult:
    reservation: UploadReservation
    created: bool


def _active_account_reservations(db: Session, *, owner_id: int) -> tuple[int, int]:
    """Sum every active reservation role billed to one account."""

    row = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            UploadReservation.quota_owner_id == owner_id,
                            UploadReservation.reserved_reference_count,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            + func.coalesce(
                func.sum(
                    case(
                        (
                            UploadReservation.library_quota_owner_id == owner_id,
                            UploadReservation.library_reserved_reference_count,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            UploadReservation.quota_owner_id == owner_id,
                            UploadReservation.reserved_size_kb,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            + func.coalesce(
                func.sum(
                    case(
                        (
                            UploadReservation.library_quota_owner_id == owner_id,
                            UploadReservation.library_reserved_size_kb,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(DurableJob, DurableJob.id == UploadReservation.id)
        .where(
            or_(
                UploadReservation.quota_owner_id == owner_id,
                UploadReservation.library_quota_owner_id == owner_id,
            ),
            DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
        )
    ).one()
    return int(row[0]), int(row[1])


def _account_has_active_digest_reservation(
    db: Session,
    *,
    account_id: int,
    content_sha256: str,
) -> bool:
    """True when the account already pays for an in-flight upload of this digest."""
    return bool(
        db.scalar(
            select(func.count(UploadReservation.id))
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                UploadReservation.content_sha256 == content_sha256,
                DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                or_(
                    UploadReservation.quota_owner_id == account_id,
                    UploadReservation.library_quota_owner_id == account_id,
                ),
            )
        )
    )


def _unattached_project_reservations(
    db: Session,
    *,
    project_id: UUID,
) -> int:
    # Every pending association consumes one Project slot even when the account
    # already owns the same canonical document elsewhere.
    return int(
        db.scalar(
            select(func.count(UploadReservation.id))
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                DurableJob.project_id == project_id,
                DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                DurableJob.document_id.is_(None),
            )
        )
        or 0
    )


def _has_active_duplicate_reservation(
    db: Session,
    *,
    requester_id: int,
    project_id: UUID | None,
    content_sha256: str,
) -> bool:
    """Detect an in-flight upload to the same logical collection.

    The caller holds the quota owner's account lock, so this check and the
    reservation insert are serialized across personal and Project uploads.
    """
    statement = (
        select(func.count(UploadReservation.id))
        .join(DurableJob, DurableJob.id == UploadReservation.id)
        .where(
            UploadReservation.content_sha256 == content_sha256,
            DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
        )
    )
    if project_id is None:
        statement = statement.where(
            DurableJob.project_id.is_(None),
            DurableJob.requested_by_id == requester_id,
        )
    else:
        statement = statement.where(DurableJob.project_id == project_id)
    return bool(db.scalar(statement))


def _locked_transfer_reservations(
    db: Session,
    *,
    owner_ids: tuple[int, ...],
    project_id: UUID,
) -> list[tuple[UploadReservation, DurableJob]]:
    """Lock both accounts' complete active-digest views for a transfer."""
    return list(
        db.execute(
            select(UploadReservation, DurableJob)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                or_(
                    UploadReservation.quota_owner_id.in_(owner_ids),
                    UploadReservation.library_quota_owner_id.in_(owner_ids),
                    DurableJob.project_id == project_id,
                ),
            )
            .order_by(UploadReservation.id)
            .with_for_update()
        )
        .tuples()
        .all()
    )


def _input_size_kb(job: DurableJob) -> int:
    input_size = job.payload.get("input_size_bytes")
    if (
        isinstance(input_size, bool)
        or not isinstance(input_size, int)
        or input_size <= 0
    ):
        raise AppError(
            code="project_transfer_reservation_invalid",
            message="An active upload does not have a valid reserved input size",
            kind=FailureKind.CONFLICT,
        )
    return math.ceil(input_size / 1024)


def _post_transfer_owners(
    reservation: UploadReservation,
    job: DurableJob,
    *,
    new_owner_id: int,
    project_id: UUID,
) -> tuple[int, int | None]:
    if job.project_id != project_id:
        return reservation.quota_owner_id, reservation.library_quota_owner_id
    library_owner_id = (
        job.requested_by_id
        if resolve_add_to_library(
            reservation.add_to_library,
            project_id=job.project_id,
        )
        and job.requested_by_id != new_owner_id
        else None
    )
    return new_owner_id, library_owner_id


def _reprice_active_reservations(
    rows: list[tuple[UploadReservation, DurableJob]],
    *,
    owner_id: int,
    new_owner_id: int,
    project_id: UUID,
    completed_digests: set[str],
) -> list[tuple[UploadReservation, DurableJob, str, int, int]]:
    """Price one owner's active digests in the post-transfer ownership view."""
    covered_digests = set(completed_digests)
    unique_rows = {
        reservation.id: (reservation, job)
        for reservation, job in rows
        if owner_id
        in _post_transfer_owners(
            reservation,
            job,
            new_owner_id=new_owner_id,
            project_id=project_id,
        )
    }
    ordered_rows = sorted(
        unique_rows.values(),
        key=lambda row: str(row[0].id),
    )
    pricing: list[tuple[UploadReservation, DurableJob, str, int, int]] = []
    for reservation, job in ordered_rows:
        primary_owner_id, _library_owner_id = _post_transfer_owners(
            reservation,
            job,
            new_owner_id=new_owner_id,
            project_id=project_id,
        )
        role = "primary" if primary_owner_id == owner_id else "library"
        if reservation.content_sha256 in covered_digests:
            pricing.append((reservation, job, role, 0, 0))
            continue
        covered_digests.add(reservation.content_sha256)
        pricing.append((reservation, job, role, 1, _input_size_kb(job)))
    return pricing


def prepare_project_quota_transfer(
    db: Session,
    *,
    project: Project,
    new_owner_id: int,
) -> ProjectQuotaTransferPlan:
    """Validate and describe every quota mutation for an ownership transfer.

    The caller must hold a row lock on ``project``. Completed account usage is
    the unique document union; Project membership and pending associations are
    still counted independently for the per-Project limit.
    """
    old_owner_id = project.owner_id
    owner_ids = tuple(sorted((old_owner_id, new_owner_id)))
    for owner_id in owner_ids:
        lock_account_resource_quota(db, user_id=owner_id)
    owners = {owner_id: get_quota_user(db, user_id=owner_id) for owner_id in owner_ids}
    limits_by_owner = {
        owner_id: get_user_entitlements(db, owner).limits.as_limits()
        for owner_id, owner in owners.items()
    }
    new_owner_limits = limits_by_owner[new_owner_id]

    owned_project_count = int(
        db.scalar(
            select(func.count(Project.id)).where(Project.owner_id == new_owner_id)
        )
        or 0
    )
    if owned_project_count + 1 > new_owner_limits[PROJECTS_KEY]:
        raise AppError(
            code="project_transfer_quota_exceeded",
            message="The new owner has reached their Project limit",
            kind=FailureKind.CONFLICT,
        )

    project_document_count = int(
        db.scalar(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project.id
            )
        )
        or 0
    )
    if project_document_count > new_owner_limits[PROJECT_PAPERS_KEY]:
        raise AppError(
            code="project_transfer_paper_quota_exceeded",
            message="This Project exceeds the new owner's per-Project paper limit",
            kind=FailureKind.CONFLICT,
        )

    active_rows = _locked_transfer_reservations(
        db,
        owner_ids=owner_ids,
        project_id=project.id,
    )

    completed_by_owner = {
        old_owner_id: resource_usage_repository.completed_documents(
            db,
            user_id=old_owner_id,
            exclude_project_id=project.id,
        ),
        new_owner_id: resource_usage_repository.completed_documents(
            db,
            user_id=new_owner_id,
            include_project_id=project.id,
        ),
    }
    pricing_by_owner = {
        owner_id: _reprice_active_reservations(
            active_rows,
            owner_id=owner_id,
            new_owner_id=new_owner_id,
            project_id=project.id,
            completed_digests={
                document.sha256 for document in completed_by_owner[owner_id]
            },
        )
        for owner_id in owner_ids
    }
    owner_states: list[ProjectQuotaOwnerState] = []
    for owner_id in owner_ids:
        documents = completed_by_owner[owner_id]
        pricing = pricing_by_owner[owner_id]
        active_count = sum(reference_count for _, _, _, reference_count, _ in pricing)
        active_size_kb = sum(size_kb for _, _, _, _, size_kb in pricing)
        limits = limits_by_owner[owner_id]
        if len(documents) + active_count > limits[PAPER_UPLOAD_KEY]:
            raise AppError(
                code="project_transfer_paper_quota_exceeded",
                message="The transfer would exceed an owner's paper limit",
                kind=FailureKind.CONFLICT,
            )
        completed_size_kb = (
            sum(document.size_bytes for document in documents) + 1023
        ) // 1024
        if completed_size_kb + active_size_kb > limits[KB_SIZE_KEY]:
            raise AppError(
                code="project_transfer_storage_quota_exceeded",
                message="The transfer would exceed an owner's storage limit",
                kind=FailureKind.CONFLICT,
            )
        owner_states.append(
            ProjectQuotaOwnerState(
                owner_id=owner_id,
                completed_document_count=len(documents),
                completed_size_kb=completed_size_kb,
                active_reference_count=active_count,
                active_size_kb=active_size_kb,
                paper_limit=limits[PAPER_UPLOAD_KEY],
                storage_limit_kb=limits[KB_SIZE_KEY],
            )
        )

    pending_project_slots = sum(
        1
        for _, job in active_rows
        if job.project_id == project.id and job.document_id is None
    )
    if (
        project_document_count + pending_project_slots
        > new_owner_limits[PROJECT_PAPERS_KEY]
    ):
        raise AppError(
            code="project_transfer_paper_quota_exceeded",
            message="This Project exceeds the new owner's per-Project paper limit",
            kind=FailureKind.CONFLICT,
        )

    pricing_assignments = {
        (reservation.id, role): (reference_count, size_kb)
        for pricing in pricing_by_owner.values()
        for reservation, _job, role, reference_count, size_kb in pricing
    }
    planned_assignments: list[ProjectReservationAssignment] = []
    for reservation, job in active_rows:
        primary_owner_id, library_owner_id = _post_transfer_owners(
            reservation,
            job,
            new_owner_id=new_owner_id,
            project_id=project.id,
        )
        current_reserved_reference_count = int(
            reservation.reserved_reference_count or 0
        )
        current_reserved_size_kb = int(reservation.reserved_size_kb or 0)
        current_library_reserved_reference_count = int(
            reservation.library_reserved_reference_count or 0
        )
        current_library_reserved_size_kb = int(
            reservation.library_reserved_size_kb or 0
        )
        reserved_reference_count = current_reserved_reference_count
        reserved_size_kb = current_reserved_size_kb
        library_reserved_reference_count = current_library_reserved_reference_count
        library_reserved_size_kb = current_library_reserved_size_kb
        if primary_owner_id in owner_ids:
            reserved_reference_count, reserved_size_kb = pricing_assignments.get(
                (reservation.id, "primary"), (0, 0)
            )
        if library_owner_id in owner_ids:
            (
                library_reserved_reference_count,
                library_reserved_size_kb,
            ) = pricing_assignments.get((reservation.id, "library"), (0, 0))
        quota_owner_id = reservation.quota_owner_id
        final_library_owner_id = reservation.library_quota_owner_id
        if job.project_id == project.id:
            quota_owner_id = primary_owner_id
            final_library_owner_id = library_owner_id
            if library_owner_id is None:
                library_reserved_reference_count = 0
                library_reserved_size_kb = 0
        planned_assignments.append(
            ProjectReservationAssignment(
                reservation_id=reservation.id,
                job_status=job.status,
                job_project_id=job.project_id,
                job_document_id=job.document_id,
                content_sha256=reservation.content_sha256,
                current_quota_owner_id=reservation.quota_owner_id,
                current_library_quota_owner_id=reservation.library_quota_owner_id,
                current_reserved_reference_count=current_reserved_reference_count,
                current_reserved_size_kb=current_reserved_size_kb,
                current_library_reserved_reference_count=(
                    current_library_reserved_reference_count
                ),
                current_library_reserved_size_kb=current_library_reserved_size_kb,
                quota_owner_id=quota_owner_id,
                library_quota_owner_id=final_library_owner_id,
                reserved_reference_count=reserved_reference_count,
                reserved_size_kb=reserved_size_kb,
                library_reserved_reference_count=(library_reserved_reference_count),
                library_reserved_size_kb=library_reserved_size_kb,
            )
        )
    assignment_payload = [
        assignment.model_dump(mode="json") for assignment in planned_assignments
    ]
    assignment_digest = hashlib.sha256(
        json.dumps(
            assignment_payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return ProjectQuotaTransferPlan(
        state=ProjectQuotaTransferState(
            project_id=project.id,
            old_owner_id=old_owner_id,
            new_owner_id=new_owner_id,
            new_owner_project_count=owned_project_count,
            new_owner_project_limit=new_owner_limits[PROJECTS_KEY],
            project_document_count=project_document_count,
            pending_project_slot_count=pending_project_slots,
            project_paper_limit=new_owner_limits[PROJECT_PAPERS_KEY],
            active_reservation_count=len(planned_assignments),
            owners=tuple(owner_states),
            reservation_assignment_digest=assignment_digest,
        ),
        assignments=tuple(planned_assignments),
    )


def apply_project_quota_transfer(
    db: Session,
    *,
    project: Project,
    new_owner_id: int,
    plan: ProjectQuotaTransferPlan,
) -> None:
    """Apply a quota plan prepared while the same account locks are held."""
    if (
        plan.state.project_id != project.id
        or plan.state.old_owner_id != project.owner_id
        or plan.state.new_owner_id != new_owner_id
    ):
        raise RuntimeError("project_quota_transfer_plan_mismatch")
    for assignment in plan.assignments:
        reservation = db.get(UploadReservation, assignment.reservation_id)
        if reservation is None:
            raise RuntimeError("project_quota_transfer_reservation_missing")
        reservation.quota_owner_id = assignment.quota_owner_id
        reservation.library_quota_owner_id = assignment.library_quota_owner_id
        reservation.reserved_reference_count = assignment.reserved_reference_count
        reservation.reserved_size_kb = assignment.reserved_size_kb
        reservation.library_reserved_reference_count = (
            assignment.library_reserved_reference_count
        )
        reservation.library_reserved_size_kb = assignment.library_reserved_size_kb
    db.flush()


def reassign_project_quota_owner(
    db: Session,
    *,
    project: Project,
    new_owner_id: int,
) -> None:
    """Prepare and apply a transfer for non-confirming application callers."""
    plan = prepare_project_quota_transfer(
        db,
        project=project,
        new_owner_id=new_owner_id,
    )
    apply_project_quota_transfer(
        db,
        project=project,
        new_owner_id=new_owner_id,
        plan=plan,
    )


def reserve_upload(
    db: Session,
    *,
    requester: Actor,
    origin_operation_id: UUID,
    correlation_id: UUID,
    project_id: UUID | None,
    input_size_bytes: int,
    original_filename: str | None,
    display_name: str,
    source_kind: str,
    content_sha256: str,
    add_to_library: bool = True,
    idempotency_key: str | None = None,
    durable_idempotency_key: str | None = None,
    job_id: UUID | None = None,
) -> UploadReservationResult:
    """Authorize once and persist the destination and quota owner before hand-off."""
    if input_size_bytes <= 0:
        raise AppError(
            code="empty_upload",
            message="The uploaded file is empty",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    if project_id is None and not add_to_library:
        raise AppError(
            code="add_to_library_false_requires_project",
            message="add_to_library=false requires a destination Project",
            kind=FailureKind.INVALID_ARGUMENT,
        )

    if project_id is None:
        owner_id = requester.id
        project = None
    else:
        access = require_project_permission_for_update(
            db,
            project_id=project_id,
            user_id=requester.id,
            permission="manage_papers",
        )
        project = access.project
        owner_id = project.owner_id

    # Library-side billing is credited to the requester only when they upload
    # into someone else's Project with add_to_library enabled; an owner's own
    # upload is already billed once through the account-unique union.
    library_billing_account_id = (
        requester.id
        if (project_id is not None and add_to_library and requester.id != owner_id)
        else None
    )
    lock_ids = tuple(
        sorted(
            {owner_id}
            | ({library_billing_account_id} if library_billing_account_id else set())
        )
    )
    for lock_id in lock_ids:
        lock_account_resource_quota(db, user_id=lock_id)

    resolved_idempotency_key = durable_idempotency_key or (
        f"pdf-ingestion:{requester.id}:{project_id or 'library'}:{idempotency_key}"
        if idempotency_key is not None
        else None
    )
    if resolved_idempotency_key is not None:
        existing_job = job_repository.find_by_idempotency_key(
            db,
            idempotency_key=resolved_idempotency_key,
        )
        if existing_job is not None:
            same_request = (
                existing_job.requested_by_id == requester.id
                and existing_job.project_id == project_id
                and existing_job.payload.get("content_sha256") == content_sha256
            )
            existing_reservation = db.get(UploadReservation, existing_job.id)
            if existing_reservation is not None:
                same_request = (
                    same_request
                    and resolve_add_to_library(
                        existing_reservation.add_to_library,
                        project_id=existing_job.project_id,
                    )
                    == add_to_library
                )
            if not same_request or existing_reservation is None:
                raise AppError(
                    code="idempotency_key_reused",
                    message="The idempotency key was already used for another request",
                    kind=FailureKind.CONFLICT,
                )
            if existing_job.status == JobStatus.CANCELLED.value:
                raise AppError(
                    code="paper_ingestion_cancelled",
                    message="This paper ingestion was cancelled",
                    kind=FailureKind.CONFLICT,
                )
            return UploadReservationResult(
                reservation=existing_reservation,
                created=False,
            )

    existing_document_id = db.scalar(
        select(Document.id).where(Document.sha256 == content_sha256)
    )
    if existing_document_id is None:
        reference_already_exists = False
    elif project_id is None:
        reference_already_exists = bool(
            db.scalar(
                select(func.count(LibraryPaper.id)).where(
                    LibraryPaper.user_id == requester.id,
                    LibraryPaper.document_id == existing_document_id,
                )
            )
        )
    else:
        reference_already_exists = bool(
            db.scalar(
                select(func.count(ProjectPaper.id)).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.document_id == existing_document_id,
                )
            )
        )
    if reference_already_exists:
        raise AppError(
            code=(
                "document_already_in_project"
                if project_id is not None
                else "document_already_in_library"
            ),
            message="This document is already in the selected collection",
            kind=FailureKind.CONFLICT,
        )

    if _has_active_duplicate_reservation(
        db,
        requester_id=requester.id,
        project_id=project_id,
        content_sha256=content_sha256,
    ):
        raise AppError(
            code="document_upload_in_progress",
            message="This document is already being uploaded to this collection",
            kind=FailureKind.CONFLICT,
        )

    owner = get_quota_user(db, user_id=owner_id)
    limits = get_user_entitlements(db, owner).limits.as_limits()
    account_already_owns_document = (
        existing_document_id is not None
        and resource_usage_repository.contains_document(
            db,
            user_id=owner_id,
            document_id=existing_document_id,
        )
    )
    active_account_reservation = _account_has_active_digest_reservation(
        db,
        account_id=owner_id,
        content_sha256=content_sha256,
    )
    adds_account_document = not (
        account_already_owns_document or active_account_reservation
    )
    reserved_reference_count = 1 if adds_account_document else 0
    reserved_size_kb = (
        math.ceil(input_size_bytes / 1024) if adds_account_document else 0
    )
    reserved_count, active_size_kb = _active_account_reservations(
        db,
        owner_id=owner_id,
    )
    completed_count = resource_usage_repository.completed_reference_count(
        db, user_id=owner.id
    )
    if (
        completed_count + reserved_count + reserved_reference_count
        > limits[PAPER_UPLOAD_KEY]
    ):
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project is not None
                else "paper_quota_exceeded"
            ),
            message="The account's paper limit has been reached",
            kind=FailureKind.PERMISSION_DENIED,
        )

    completed_size_kb = resource_usage_repository.completed_storage_kb(
        db, user_id=owner.id
    )
    if completed_size_kb + active_size_kb + reserved_size_kb > limits[KB_SIZE_KEY]:
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project is not None
                else "storage_quota_exceeded"
            ),
            message="The account's storage limit would be exceeded",
            kind=FailureKind.PERMISSION_DENIED,
        )

    # Library-side capacity: billed to the requester's own account only when
    # they do not already own the digest. The project owner's side is never
    # double-charged for the same Document (account-unique union).
    library_reserved_reference_count = 0
    library_reserved_size_kb = 0
    if library_billing_account_id is not None:
        library_user = get_quota_user(db, user_id=library_billing_account_id)
        library_limits = get_user_entitlements(db, library_user).limits.as_limits()
        requester_owns_document = (
            existing_document_id is not None
            and resource_usage_repository.contains_document(
                db,
                user_id=library_billing_account_id,
                document_id=existing_document_id,
            )
        )
        requester_has_library_membership = existing_document_id is not None and bool(
            db.scalar(
                select(func.count(LibraryPaper.id)).where(
                    LibraryPaper.user_id == library_billing_account_id,
                    LibraryPaper.document_id == existing_document_id,
                )
            )
        )
        requester_active_reservation = _account_has_active_digest_reservation(
            db,
            account_id=library_billing_account_id,
            content_sha256=content_sha256,
        )
        adds_library_document = not (
            requester_owns_document
            or requester_has_library_membership
            or requester_active_reservation
        )
        if adds_library_document:
            library_reserved_reference_count = 1
            library_reserved_size_kb = math.ceil(input_size_bytes / 1024)
            library_reserved_count, library_active_size_kb = (
                _active_account_reservations(
                    db,
                    owner_id=library_billing_account_id,
                )
            )
            library_completed_count = (
                resource_usage_repository.completed_reference_count(
                    db, user_id=library_user.id
                )
            )
            if (
                library_completed_count
                + library_reserved_count
                + library_reserved_reference_count
                > library_limits[PAPER_UPLOAD_KEY]
            ):
                raise AppError(
                    code="paper_quota_exceeded",
                    message="The account's paper limit has been reached",
                    kind=FailureKind.PERMISSION_DENIED,
                )
            library_completed_size_kb = resource_usage_repository.completed_storage_kb(
                db, user_id=library_user.id
            )
            if (
                library_completed_size_kb
                + library_active_size_kb
                + library_reserved_size_kb
                > library_limits[KB_SIZE_KEY]
            ):
                raise AppError(
                    code="storage_quota_exceeded",
                    message="The account's storage limit would be exceeded",
                    kind=FailureKind.PERMISSION_DENIED,
                )

    if project is not None:
        linked_count = int(
            db.scalar(
                select(func.count(ProjectPaper.id)).where(
                    ProjectPaper.project_id == project.id
                )
            )
            or 0
        )
        waiting_count = _unattached_project_reservations(
            db,
            project_id=project.id,
        )
        if linked_count + waiting_count + 1 > limits[PROJECT_PAPERS_KEY]:
            raise AppError(
                code="project_paper_quota_exceeded",
                message="The Project's paper limit has been reached",
                kind=FailureKind.PERMISSION_DENIED,
            )

    job_id = job_id or uuid4()
    persisted_job = job_repository.create(
        db,
        request=CreateJob(
            operation=JobOperation.PDF_PROCESS,
            requested_by_id=requester.id,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            project_id=project_id,
            idempotency_key=resolved_idempotency_key or f"pdf-reservation:{job_id}",
            payload={
                "content_sha256": content_sha256,
                "original_filename": original_filename,
                "input_size_bytes": input_size_bytes,
            },
            job_id=job_id,
        ),
    )
    durable_job = persisted_job.job
    reservation = UploadReservation(
        id=durable_job.id,
        quota_owner_id=owner_id,
        reserved_size_kb=reserved_size_kb,
        reserved_reference_count=reserved_reference_count,
        content_sha256=content_sha256,
        add_to_library=add_to_library,
        library_quota_owner_id=library_billing_account_id,
        library_reserved_reference_count=library_reserved_reference_count,
        library_reserved_size_kb=library_reserved_size_kb,
        original_filename=original_filename,
        display_name=display_name,
        source_kind=source_kind,
    )
    reservation.job = durable_job
    db.add(reservation)
    db.flush()
    db.refresh(reservation)
    return UploadReservationResult(
        reservation=reservation,
        created=True,
    )
