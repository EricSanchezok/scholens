"""Cross-module persistence for durable paper-ingestion reservations."""

import uuid
from datetime import datetime, timezone

from app.database.models import (
    Document,
    DurableJob,
    JobStatus,
    UploadReservation,
    ProjectPaper,
)
from app.modules.projects.infrastructure.access import get_project_access
from app.shared.application import Actor
from sqlalchemy import select
from sqlalchemy.orm import Session


class UploadReservationRepository:
    """Explicit persistence for PDF upload reservations."""

    @staticmethod
    def get(
        db: Session,
        *,
        id: object,
        user: Actor,
    ) -> UploadReservation | None:
        try:
            job_id = uuid.UUID(str(id))
        except (TypeError, ValueError):
            return None
        return db.scalar(
            select(UploadReservation)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                UploadReservation.id == job_id,
                DurableJob.requested_by_id == user.id,
            )
        )

    @staticmethod
    def get_by(
        db: Session,
        *,
        id: object,
        task_id: str | None = None,
    ) -> UploadReservation | None:
        try:
            job_id = uuid.UUID(str(id))
        except (TypeError, ValueError):
            return None
        if task_id is not None and task_id != str(job_id):
            return None
        statement = select(UploadReservation).where(UploadReservation.id == job_id)
        return db.scalar(statement)

    @staticmethod
    def _set_status(
        db: Session,
        *,
        job: UploadReservation,
        status: JobStatus,
        error_code: str | None = None,
    ) -> UploadReservation:
        job.job.status = status.value
        job.job.error_code = error_code
        now = datetime.now(timezone.utc)
        if status == JobStatus.RUNNING:
            job.job.started_at = now
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            job.job.completed_at = now
        db.flush()
        db.refresh(job)
        return job

    def mark_as_running(
        self, db: Session, *, job_id: str, user: Actor
    ) -> UploadReservation | None:
        """Mark a job as running and set started_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self._set_status(db, job=job, status=JobStatus.RUNNING)
        return None

    def mark_as_completed(
        self, db: Session, *, job_id: str, user: Actor
    ) -> UploadReservation | None:
        """Mark a job as completed and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self._set_status(db, job=job, status=JobStatus.COMPLETED)
        return None

    def mark_as_failed(
        self,
        db: Session,
        *,
        job_id: str,
        user: Actor,
        error_code: str = "upload_failed",
    ) -> UploadReservation | None:
        """Mark a job as failed and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self._set_status(
                db,
                job=job,
                status=JobStatus.FAILED,
                error_code=error_code,
            )
        return None

    def mark_as_cancelled(
        self, db: Session, *, job_id: str, user: Actor
    ) -> UploadReservation | None:
        """Mark a job as cancelled and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self._set_status(db, job=job, status=JobStatus.CANCELLED)
        return None

    def get_user_jobs(
        self, db: Session, *, user: Actor, skip: int = 0, limit: int = 100
    ) -> list[UploadReservation]:
        """Get all paper upload jobs for a specific user"""
        return list(
            db.scalars(
                select(UploadReservation)
                .join(DurableJob, DurableJob.id == UploadReservation.id)
                .where(DurableJob.requested_by_id == user.id)
                .order_by(DurableJob.created_at.desc())
                .offset(skip)
                .limit(limit)
            ).all()
        )

    def get_in_progress_jobs_for_project(
        self, db: Session, *, project_id: uuid.UUID, user: Actor
    ) -> list[tuple[UploadReservation, Document]]:
        """
        Get upload jobs that are still in progress for a project, paired with
        their paper record.

        Atomic ingestion creates the Document, ProjectPaper, durable Job and
        outbox dispatch before the request is accepted. Durable leases own
        recovery and hard timeouts, so every pending/running row remains a
        legitimate task until it reaches a terminal state.
        """
        # Only the owner and collaborators may see in-progress Project uploads.
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return []

        statement = (
            select(UploadReservation, Document)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .join(Document, Document.id == DurableJob.document_id)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(
                ProjectPaper.project_id == project_id,
                DurableJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
            .order_by(DurableJob.created_at.asc())
        )
        return list(db.execute(statement).tuples().all())


# Create a single instance to use throughout the application
upload_reservation_repository = UploadReservationRepository()
