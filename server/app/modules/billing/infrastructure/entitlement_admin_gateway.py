"""SQLAlchemy adapter for audited entitlement administration."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.billing.application.entitlement_admin import (
    GrantRecord,
    OverrideRecord,
)
from app.modules.billing.infrastructure.entitlement_repository import (
    entitlement_repository,
)
from app.modules.billing.infrastructure.account_locks import (
    lock_account_resource_quota,
)
from app.modules.billing.infrastructure.models import (
    AccountPlanGrant,
    AccountQuotaOverride,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class TargetIdentityLocker(Protocol):
    def __call__(self, *, user_id: int) -> Actor | None: ...


class SqlAlchemyEntitlementAdminGateway:
    def __init__(
        self,
        db: Session,
        *,
        lock_target_identity: TargetIdentityLocker,
    ) -> None:
        self._db = db
        self._lock_target_identity = lock_target_identity

    def lock_account(self, *, user_id: int) -> None:
        lock_account_resource_quota(self._db, user_id=user_id)

    def lock_target_identity(self, *, user_id: int) -> Actor | None:
        return self._lock_target_identity(user_id=user_id)

    @staticmethod
    def _grant(model: AccountPlanGrant) -> GrantRecord:
        return GrantRecord(
            id=model.id,
            user_id=model.user_id,
            expires_at=model.expires_at,
        )

    @staticmethod
    def _override(model: AccountQuotaOverride) -> OverrideRecord:
        return OverrideRecord(
            id=model.id,
            user_id=model.user_id,
            resource_key=model.resource_key,
            limit_value=model.limit_value,
            expires_at=model.expires_at,
        )

    def current_grant(self, *, user_id: int) -> GrantRecord | None:
        model = entitlement_repository.unrevoked_plan_grant(
            self._db,
            user_id=user_id,
            lock=True,
        )
        return self._grant(model) if model is not None else None

    def create_grant(
        self,
        *,
        user_id: int,
        granted_by_user_id: int,
        granted_at: datetime,
        expires_at: datetime,
        reason: str,
    ) -> GrantRecord:
        return self._grant(
            entitlement_repository.create_plan_grant(
                self._db,
                user_id=user_id,
                granted_by_user_id=granted_by_user_id,
                granted_at=granted_at,
                expires_at=expires_at,
                reason=reason,
            )
        )

    def revoke_grant(
        self,
        *,
        grant_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        grant = self._db.get(AccountPlanGrant, grant_id)
        if grant is None:
            raise RuntimeError("plan_grant_disappeared")
        entitlement_repository.revoke_plan_grant(
            self._db,
            grant=grant,
            revoked_by_user_id=revoked_by_user_id,
            revoked_at=revoked_at,
            reason=reason,
        )

    def current_override(
        self,
        *,
        user_id: int,
        resource_key: str,
    ) -> OverrideRecord | None:
        model = entitlement_repository.unrevoked_quota_override(
            self._db,
            user_id=user_id,
            resource_key=resource_key,
            lock=True,
        )
        return self._override(model) if model is not None else None

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
    ) -> OverrideRecord:
        return self._override(
            entitlement_repository.create_quota_override(
                self._db,
                user_id=user_id,
                resource_key=resource_key,
                limit_value=limit_value,
                set_by_user_id=set_by_user_id,
                set_at=set_at,
                expires_at=expires_at,
                reason=reason,
            )
        )

    def revoke_override(
        self,
        *,
        override_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        override = self._db.get(AccountQuotaOverride, override_id)
        if override is None:
            raise RuntimeError("quota_override_disappeared")
        entitlement_repository.revoke_quota_override(
            self._db,
            override=override,
            revoked_by_user_id=revoked_by_user_id,
            revoked_at=revoked_at,
            reason=reason,
        )


__all__ = ["SqlAlchemyEntitlementAdminGateway"]
