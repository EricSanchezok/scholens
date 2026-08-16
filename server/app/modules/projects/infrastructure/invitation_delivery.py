"""Recoverable delivery loop for Project invitation email."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.modules.notifications.application import (
    EmailDeliveryError,
    TransactionalEmailSender,
)
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.modules.projects.infrastructure.invitation_email import (
    build_project_invitation_email,
)
from app.modules.projects.infrastructure.models import ProjectInvitation
from scholens_observability import add_counter, instrumented_span, record_histogram

logger = logging.getLogger(__name__)

DELIVERY_BATCH_SIZE = 20
DELIVERY_IDLE_SECONDS = float(
    os.getenv("PROJECT_INVITATION_DELIVERY_INTERVAL_SECONDS", "1")
)
DELIVERY_MAX_ATTEMPTS = 8
DELIVERY_MAX_BACKOFF_SECONDS = 3_600
DELIVERY_LEASE = timedelta(
    seconds=float(os.getenv("PROJECT_INVITATION_DELIVERY_LEASE_SECONDS", "45"))
)


@dataclass(frozen=True, slots=True)
class ReservedProjectInvitationDelivery:
    invitation_id: UUID
    token_revision: int
    lease_id: UUID
    attempt_count: int
    enqueued_at: datetime
    recipient_email: str = field(repr=False)
    inviter_name: str
    project_title: str


class ProjectInvitationDeliveryRepository:
    def recover_expired_leases(
        self,
        db: Session,
        *,
        now: datetime,
    ) -> int:
        exhausted = db.execute(
            update(ProjectInvitation)
            .where(
                ProjectInvitation.delivery_status == "pending",
                ProjectInvitation.delivery_lease_expires_at.is_not(None),
                ProjectInvitation.delivery_lease_expires_at <= now,
                ProjectInvitation.delivery_attempt_count >= DELIVERY_MAX_ATTEMPTS,
            )
            .values(
                delivery_status="failed",
                delivery_failure_code="delivery_lease_expired",
                delivery_lease_id=None,
                delivery_lease_expires_at=None,
            )
        )
        recoverable = db.execute(
            update(ProjectInvitation)
            .where(
                ProjectInvitation.delivery_status == "pending",
                ProjectInvitation.delivery_lease_expires_at.is_not(None),
                ProjectInvitation.delivery_lease_expires_at <= now,
                ProjectInvitation.delivery_attempt_count < DELIVERY_MAX_ATTEMPTS,
            )
            .values(
                delivery_lease_id=None,
                delivery_lease_expires_at=None,
            )
        )
        return int(exhausted.rowcount or 0) + int(recoverable.rowcount or 0)

    def reserve(
        self,
        db: Session,
        *,
        now: datetime,
        lease: timedelta,
        limit: int,
    ) -> tuple[ReservedProjectInvitationDelivery, ...]:
        invitations = list(
            db.scalars(
                select(ProjectInvitation)
                .where(
                    ProjectInvitation.delivery_status == "pending",
                    ProjectInvitation.delivery_attempt_count < DELIVERY_MAX_ATTEMPTS,
                    ProjectInvitation.delivery_next_attempt_at <= now,
                    ProjectInvitation.accepted_at.is_(None),
                    ProjectInvitation.revoked_at.is_(None),
                    ProjectInvitation.expires_at > now,
                    or_(
                        ProjectInvitation.delivery_lease_expires_at.is_(None),
                        ProjectInvitation.delivery_lease_expires_at <= now,
                    ),
                )
                .options(
                    joinedload(ProjectInvitation.project),
                    joinedload(ProjectInvitation.invited_by),
                )
                .order_by(
                    ProjectInvitation.delivery_next_attempt_at,
                    ProjectInvitation.created_at,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        reserved: list[ReservedProjectInvitationDelivery] = []
        for invitation in invitations:
            lease_id = uuid.uuid4()
            invitation.delivery_attempt_count += 1
            invitation.delivery_lease_id = lease_id
            invitation.delivery_lease_expires_at = now + lease
            reserved.append(
                ReservedProjectInvitationDelivery(
                    invitation_id=invitation.id,
                    token_revision=invitation.token_revision,
                    lease_id=lease_id,
                    attempt_count=invitation.delivery_attempt_count,
                    enqueued_at=invitation.delivery_next_attempt_at,
                    recipient_email=invitation.email,
                    inviter_name=(
                        invitation.invited_by.display_name
                        or invitation.invited_by.email
                    ),
                    project_title=invitation.project.title,
                )
            )
        db.flush()
        return tuple(reserved)

    def is_active(
        self,
        db: Session,
        *,
        delivery: ReservedProjectInvitationDelivery,
        now: datetime,
    ) -> bool:
        return (
            db.scalar(
                select(ProjectInvitation.id).where(
                    ProjectInvitation.id == delivery.invitation_id,
                    ProjectInvitation.token_revision == delivery.token_revision,
                    ProjectInvitation.delivery_status == "pending",
                    ProjectInvitation.delivery_lease_id == delivery.lease_id,
                    ProjectInvitation.accepted_at.is_(None),
                    ProjectInvitation.revoked_at.is_(None),
                    ProjectInvitation.expires_at > now,
                )
            )
            is not None
        )

    def complete(
        self,
        db: Session,
        *,
        delivery: ReservedProjectInvitationDelivery,
        delivered_at: datetime,
    ) -> bool:
        result = db.execute(
            update(ProjectInvitation)
            .where(
                ProjectInvitation.id == delivery.invitation_id,
                ProjectInvitation.token_revision == delivery.token_revision,
                ProjectInvitation.delivery_status == "pending",
                ProjectInvitation.delivery_lease_id == delivery.lease_id,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
            )
            .values(
                delivery_status="sent",
                delivered_at=delivered_at,
                delivery_failure_code=None,
                delivery_lease_id=None,
                delivery_lease_expires_at=None,
            )
        )
        return bool(result.rowcount)

    def fail(
        self,
        db: Session,
        *,
        delivery: ReservedProjectInvitationDelivery,
        error: EmailDeliveryError,
        next_attempt_at: datetime,
    ) -> tuple[bool, str]:
        exhausted = delivery.attempt_count >= DELIVERY_MAX_ATTEMPTS
        terminal = not error.transient or exhausted
        status = "failed" if terminal else "pending"
        result = db.execute(
            update(ProjectInvitation)
            .where(
                ProjectInvitation.id == delivery.invitation_id,
                ProjectInvitation.token_revision == delivery.token_revision,
                ProjectInvitation.delivery_status == "pending",
                ProjectInvitation.delivery_lease_id == delivery.lease_id,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
            )
            .values(
                delivery_status=status,
                delivery_next_attempt_at=next_attempt_at,
                delivery_failure_code=error.code[:80],
                delivery_lease_id=None,
                delivery_lease_expires_at=None,
            )
        )
        return bool(result.rowcount), status


project_invitation_delivery_repository = ProjectInvitationDeliveryRepository()


class ProjectInvitationDeliverySupervisor:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        sender: TransactionalEmailSender,
        token_codec: ProjectInvitationTokenCodec,
        client_domain: str,
    ) -> None:
        self._session_factory = session_factory
        self._sender = sender
        self._token_codec = token_codec
        self._client_domain = client_domain

    def _reserve(self, *, limit: int) -> tuple[ReservedProjectInvitationDelivery, ...]:
        now = datetime.now(UTC)
        with self._session_factory() as db:
            recovered = project_invitation_delivery_repository.recover_expired_leases(
                db,
                now=now,
            )
            deliveries = project_invitation_delivery_repository.reserve(
                db,
                now=now,
                lease=DELIVERY_LEASE,
                limit=limit,
            )
            db.commit()
        if recovered:
            logger.warning(
                "email.project_invitation.leases_recovered",
                extra={"recovered_count": recovered},
            )
        return deliveries

    def _active(self, delivery: ReservedProjectInvitationDelivery) -> bool:
        with self._session_factory() as db:
            return project_invitation_delivery_repository.is_active(
                db,
                delivery=delivery,
                now=datetime.now(UTC),
            )

    def _complete(self, delivery: ReservedProjectInvitationDelivery) -> bool:
        with self._session_factory() as db:
            changed = project_invitation_delivery_repository.complete(
                db,
                delivery=delivery,
                delivered_at=datetime.now(UTC),
            )
            db.commit()
        return changed

    def _fail(
        self,
        delivery: ReservedProjectInvitationDelivery,
        error: EmailDeliveryError,
    ) -> tuple[bool, str]:
        delay = min(
            DELIVERY_MAX_BACKOFF_SECONDS,
            2 ** min(delivery.attempt_count, 12),
        )
        with self._session_factory() as db:
            changed, status = project_invitation_delivery_repository.fail(
                db,
                delivery=delivery,
                error=error,
                next_attempt_at=datetime.now(UTC) + timedelta(seconds=delay),
            )
            db.commit()
        return changed, status

    async def deliver_once(self, *, limit: int = DELIVERY_BATCH_SIZE) -> int:
        started = monotonic()
        sent = 0
        deliveries = await asyncio.to_thread(self._reserve, limit=limit)
        with instrumented_span(
            "email.project_invitation.dispatch",
            attributes={"email.delivery.batch_size": len(deliveries)},
        ):
            for delivery in deliveries:
                if not await asyncio.to_thread(self._active, delivery):
                    add_counter(
                        "scholens.email.deliveries",
                        attributes={
                            "kind": "project_invitation",
                            "outcome": "cancelled",
                        },
                    )
                    continue
                message = build_project_invitation_email(
                    inviter_name=delivery.inviter_name,
                    project_title=delivery.project_title,
                    invitation_token=self._token_codec.encode(
                        invitation_id=delivery.invitation_id,
                        revision=delivery.token_revision,
                    ),
                    client_domain=self._client_domain,
                )
                outcome = "sent"
                try:
                    await self._sender.send(
                        to_address=delivery.recipient_email,
                        message=message,
                    )
                except EmailDeliveryError as exc:
                    changed, delivery_status = await asyncio.to_thread(
                        self._fail,
                        delivery,
                        exc,
                    )
                    outcome = "failed" if delivery_status == "failed" else "retry"
                    logger.warning(
                        "email.project_invitation.delivery_failed",
                        extra={
                            "invitation_id": str(delivery.invitation_id),
                            "attempt": delivery.attempt_count,
                            "failure_code": exc.code,
                            "outcome": outcome,
                            "lease_owned": changed,
                        },
                    )
                else:
                    if await asyncio.to_thread(self._complete, delivery):
                        sent += 1
                    else:
                        outcome = "lease_superseded"
                add_counter(
                    "scholens.email.deliveries",
                    attributes={"kind": "project_invitation", "outcome": outcome},
                )
                record_histogram(
                    "scholens.email.delivery_delay",
                    max(0, (datetime.now(UTC) - delivery.enqueued_at).total_seconds()),
                    unit="s",
                    attributes={"kind": "project_invitation", "outcome": outcome},
                )
        record_histogram(
            "scholens.email.delivery_batch_duration",
            (monotonic() - started) * 1000,
            unit="ms",
        )
        return sent

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                sent = await self.deliver_once()
            except Exception:
                logger.exception("email.project_invitation.dispatch_failed")
                sent = 0
            if sent:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=DELIVERY_IDLE_SECONDS)
            except TimeoutError:
                pass


__all__ = [
    "ProjectInvitationDeliveryRepository",
    "ProjectInvitationDeliverySupervisor",
    "ReservedProjectInvitationDelivery",
    "project_invitation_delivery_repository",
]
