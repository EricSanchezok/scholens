"""Audited administrator commands for non-billing entitlements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.billing.domain import (
    KB_SIZE_KEY,
    PAPER_UPLOAD_KEY,
    PROJECT_PAPERS_KEY,
    PROJECTS_KEY,
    TOKEN_CREDITS_KEY,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, Clock, OperationContext
from app.shared.domain import AppError, FailureKind

ENTITLEMENT_PLAN_GRANTED = OperationAction("entitlement.plan_granted")
ENTITLEMENT_PLAN_REVOKED = OperationAction("entitlement.plan_revoked")
ENTITLEMENT_QUOTA_SET = OperationAction("entitlement.quota_set")
ENTITLEMENT_QUOTA_CLEARED = OperationAction("entitlement.quota_cleared")
QUOTA_KEYS = frozenset(
    {
        PAPER_UPLOAD_KEY,
        KB_SIZE_KEY,
        TOKEN_CREDITS_KEY,
        PROJECTS_KEY,
        PROJECT_PAPERS_KEY,
    }
)
OPERATOR_RETRY_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class GrantRecord:
    id: UUID
    user_id: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    id: UUID
    user_id: int
    resource_key: str
    limit_value: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MutationResult:
    user_id: int
    resource_id: UUID | None
    changed: bool


class EntitlementAdminGateway(Protocol):
    def lock_account(self, *, user_id: int) -> None: ...

    def lock_target_identity(self, *, user_id: int) -> Actor | None: ...

    def current_grant(self, *, user_id: int) -> GrantRecord | None: ...

    def create_grant(
        self,
        *,
        user_id: int,
        granted_by_user_id: int,
        granted_at: datetime,
        expires_at: datetime,
        reason: str,
    ) -> GrantRecord: ...

    def revoke_grant(
        self,
        *,
        grant_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None: ...

    def current_override(
        self,
        *,
        user_id: int,
        resource_key: str,
    ) -> OverrideRecord | None: ...

    def create_override(
        self,
        *,
        user_id: int,
        resource_key: str,
        limit_value: int,
        set_by_user_id: int,
        set_at: datetime,
        expires_at: datetime,
        reason: str,
    ) -> OverrideRecord: ...

    def revoke_override(
        self,
        *,
        override_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None: ...


class EntitlementAdmin:
    def __init__(
        self,
        gateway: EntitlementAdminGateway,
        *,
        journal: OperationJournal,
        clock: Clock,
    ) -> None:
        self._gateway = gateway
        self._journal = journal
        self._clock = clock

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        if not actor.is_active or actor.is_blocked or not actor.is_admin:
            raise AppError(
                code="admin_required",
                message="Administrator access is required",
                kind=FailureKind.PERMISSION_DENIED,
            )

    @staticmethod
    def _require_target(target: Actor) -> None:
        if not target.is_active or target.is_blocked or not target.email_verified:
            raise AppError(
                code="entitlement_target_ineligible",
                message="Entitlements require an active verified account",
                kind=FailureKind.CONFLICT,
            )

    def _lock_targets(
        self,
        targets: tuple[Actor, ...],
        *,
        require_eligible: bool,
    ) -> tuple[Actor, ...]:
        """Lock and reload target identity facts inside the mutation UoW."""
        user_ids = sorted({target.id for target in targets})
        if not user_ids:
            raise AppError(
                code="entitlement_target_required",
                message="At least one target account is required",
                kind=FailureKind.INVALID_ARGUMENT,
            )

        locked_targets: list[Actor] = []
        for user_id in user_ids:
            self._gateway.lock_account(user_id=user_id)
            target = self._gateway.lock_target_identity(user_id=user_id)
            if target is None:
                raise AppError(
                    code="entitlement_target_ineligible",
                    message="Entitlements require an active verified account",
                    kind=FailureKind.CONFLICT,
                )
            if require_eligible:
                self._require_target(target)
            locked_targets.append(target)
        return tuple(locked_targets)

    def grant_researcher(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        targets: tuple[Actor, ...],
        days: int,
        reason: str,
    ) -> tuple[MutationResult, ...]:
        self._require_admin(actor)
        if not 1 <= days <= 365:
            raise AppError(
                code="entitlement_duration_invalid",
                message="Plan grants must last between 1 and 365 days",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise AppError(
                code="entitlement_reason_invalid",
                message="A reason of at most 500 characters is required",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        locked_targets = self._lock_targets(targets, require_eligible=True)
        now = self._clock.now()
        expires_at = now + timedelta(days=days)
        results: list[MutationResult] = []
        for target in locked_targets:
            existing = self._gateway.current_grant(user_id=target.id)
            # Re-running a duration-based operator command must not churn the
            # grant merely because its wall clock moved by a few seconds.
            if (
                existing is not None
                and existing.expires_at >= expires_at - OPERATOR_RETRY_TOLERANCE
            ):
                results.append(
                    MutationResult(
                        user_id=target.id,
                        resource_id=existing.id,
                        changed=False,
                    )
                )
                continue
            if existing is not None:
                self._gateway.revoke_grant(
                    grant_id=existing.id,
                    revoked_by_user_id=actor.id,
                    revoked_at=now,
                    reason=normalized_reason,
                )
            grant = self._gateway.create_grant(
                user_id=target.id,
                granted_by_user_id=actor.id,
                granted_at=now,
                expires_at=expires_at,
                reason=normalized_reason,
            )
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ENTITLEMENT_PLAN_GRANTED,
                resources=(
                    ResourceRef("user", str(target.id)),
                    ResourceRef("plan_grant", str(grant.id)),
                ),
            )
            results.append(
                MutationResult(user_id=target.id, resource_id=grant.id, changed=True)
            )
        return tuple(results)

    def revoke_researcher(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        target: Actor,
        reason: str,
    ) -> MutationResult:
        return self.revoke_researcher_batch(
            actor=actor,
            operation=operation,
            targets=(target,),
            reason=reason,
        )[0]

    def revoke_researcher_batch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        targets: tuple[Actor, ...],
        reason: str,
    ) -> tuple[MutationResult, ...]:
        self._require_admin(actor)
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise AppError(
                code="entitlement_reason_invalid",
                message="A reason of at most 500 characters is required",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        locked_targets = self._lock_targets(targets, require_eligible=False)
        now = self._clock.now()
        results: list[MutationResult] = []
        for target in locked_targets:
            existing = self._gateway.current_grant(user_id=target.id)
            if existing is None:
                results.append(
                    MutationResult(
                        user_id=target.id,
                        resource_id=None,
                        changed=False,
                    )
                )
                continue
            self._gateway.revoke_grant(
                grant_id=existing.id,
                revoked_by_user_id=actor.id,
                revoked_at=now,
                reason=normalized_reason,
            )
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ENTITLEMENT_PLAN_REVOKED,
                resources=(
                    ResourceRef("user", str(target.id)),
                    ResourceRef("plan_grant", str(existing.id)),
                ),
            )
            results.append(
                MutationResult(
                    user_id=target.id,
                    resource_id=existing.id,
                    changed=True,
                )
            )
        return tuple(results)

    def set_quota(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        target: Actor,
        resource_key: str,
        limit_value: int,
        days: int,
        reason: str,
    ) -> MutationResult:
        self._require_admin(actor)
        if resource_key not in QUOTA_KEYS or limit_value < 0:
            raise AppError(
                code="quota_override_invalid",
                message="The quota resource or value is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if not 1 <= days <= 365:
            raise AppError(
                code="quota_override_duration_invalid",
                message="Quota overrides must last between 1 and 365 days",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise AppError(
                code="entitlement_reason_invalid",
                message="A reason of at most 500 characters is required",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        locked_target = self._lock_targets((target,), require_eligible=True)[0]
        now = self._clock.now()
        expires_at = now + timedelta(days=days)
        existing = self._gateway.current_override(
            user_id=locked_target.id,
            resource_key=resource_key,
        )
        if (
            existing is not None
            and existing.limit_value == limit_value
            and existing.expires_at >= expires_at - OPERATOR_RETRY_TOLERANCE
        ):
            return MutationResult(
                user_id=locked_target.id,
                resource_id=existing.id,
                changed=False,
            )
        if existing is not None:
            self._gateway.revoke_override(
                override_id=existing.id,
                revoked_by_user_id=actor.id,
                revoked_at=now,
                reason=normalized_reason,
            )
        created = self._gateway.create_override(
            user_id=locked_target.id,
            resource_key=resource_key,
            limit_value=limit_value,
            set_by_user_id=actor.id,
            set_at=now,
            expires_at=expires_at,
            reason=normalized_reason,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=ENTITLEMENT_QUOTA_SET,
            resources=(
                ResourceRef("user", str(locked_target.id)),
                ResourceRef("quota_override", str(created.id)),
            ),
        )
        return MutationResult(
            user_id=locked_target.id,
            resource_id=created.id,
            changed=True,
        )

    def clear_quota(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        target: Actor,
        resource_key: str,
        reason: str,
    ) -> MutationResult:
        self._require_admin(actor)
        if resource_key not in QUOTA_KEYS:
            raise AppError(
                code="quota_override_invalid",
                message="The quota resource is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise AppError(
                code="entitlement_reason_invalid",
                message="A reason of at most 500 characters is required",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        locked_target = self._lock_targets((target,), require_eligible=False)[0]
        existing = self._gateway.current_override(
            user_id=locked_target.id,
            resource_key=resource_key,
        )
        if existing is None:
            return MutationResult(
                user_id=locked_target.id,
                resource_id=None,
                changed=False,
            )
        self._gateway.revoke_override(
            override_id=existing.id,
            revoked_by_user_id=actor.id,
            revoked_at=self._clock.now(),
            reason=normalized_reason,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=ENTITLEMENT_QUOTA_CLEARED,
            resources=(
                ResourceRef("user", str(locked_target.id)),
                ResourceRef("quota_override", str(existing.id)),
            ),
        )
        return MutationResult(
            user_id=locked_target.id,
            resource_id=existing.id,
            changed=True,
        )


__all__ = [
    "EntitlementAdmin",
    "EntitlementAdminGateway",
    "GrantRecord",
    "MutationResult",
    "OverrideRecord",
    "QUOTA_KEYS",
]
