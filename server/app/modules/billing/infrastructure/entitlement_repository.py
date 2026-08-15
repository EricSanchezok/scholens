"""Persistence queries for product-owned entitlement grants and overrides."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.modules.billing.infrastructure.models import (
    AccountPlanGrant,
    AccountQuotaOverride,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class EntitlementRepository:
    def unrevoked_plan_grant(
        self,
        db: Session,
        *,
        user_id: int,
        lock: bool = False,
    ) -> AccountPlanGrant | None:
        statement = (
            select(AccountPlanGrant)
            .where(
                AccountPlanGrant.user_id == user_id,
                AccountPlanGrant.revoked_at.is_(None),
            )
            .order_by(AccountPlanGrant.created_at.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        return db.scalars(statement).first()

    def active_plan_grant(
        self,
        db: Session,
        *,
        user_id: int,
        now: datetime,
    ) -> AccountPlanGrant | None:
        return db.scalars(
            select(AccountPlanGrant)
            .where(
                AccountPlanGrant.user_id == user_id,
                AccountPlanGrant.revoked_at.is_(None),
                AccountPlanGrant.expires_at > now,
            )
            .order_by(AccountPlanGrant.created_at.desc())
            .limit(1)
        ).first()

    def active_quota_overrides(
        self,
        db: Session,
        *,
        user_id: int,
        now: datetime,
    ) -> list[AccountQuotaOverride]:
        return list(
            db.scalars(
                select(AccountQuotaOverride)
                .where(
                    AccountQuotaOverride.user_id == user_id,
                    AccountQuotaOverride.revoked_at.is_(None),
                    AccountQuotaOverride.expires_at > now,
                )
                .order_by(AccountQuotaOverride.resource_key)
            ).all()
        )

    def unrevoked_quota_override(
        self,
        db: Session,
        *,
        user_id: int,
        resource_key: str,
        lock: bool = False,
    ) -> AccountQuotaOverride | None:
        statement = (
            select(AccountQuotaOverride)
            .where(
                AccountQuotaOverride.user_id == user_id,
                AccountQuotaOverride.resource_key == resource_key,
                AccountQuotaOverride.revoked_at.is_(None),
            )
            .order_by(AccountQuotaOverride.created_at.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        return db.scalars(statement).first()

    @staticmethod
    def create_plan_grant(
        db: Session,
        *,
        user_id: int,
        granted_by_user_id: int,
        granted_at: datetime,
        expires_at: datetime,
        reason: str,
        grant_id: UUID | None = None,
    ) -> AccountPlanGrant:
        grant = AccountPlanGrant(
            id=grant_id or uuid4(),
            user_id=user_id,
            plan="researcher",
            granted_by_user_id=granted_by_user_id,
            created_at=granted_at,
            updated_at=granted_at,
            expires_at=expires_at,
            reason=reason,
        )
        db.add(grant)
        db.flush()
        return grant

    @staticmethod
    def revoke_plan_grant(
        db: Session,
        *,
        grant: AccountPlanGrant,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        grant.revoked_at = revoked_at
        grant.revoked_by_user_id = revoked_by_user_id
        grant.revocation_reason = reason
        db.flush()

    @staticmethod
    def create_quota_override(
        db: Session,
        *,
        user_id: int,
        resource_key: str,
        limit_value: int,
        set_by_user_id: int,
        set_at: datetime,
        expires_at: datetime,
        reason: str,
        override_id: UUID | None = None,
    ) -> AccountQuotaOverride:
        override = AccountQuotaOverride(
            id=override_id or uuid4(),
            user_id=user_id,
            resource_key=resource_key,
            limit_value=limit_value,
            set_by_user_id=set_by_user_id,
            created_at=set_at,
            updated_at=set_at,
            expires_at=expires_at,
            reason=reason,
        )
        db.add(override)
        db.flush()
        return override

    @staticmethod
    def revoke_quota_override(
        db: Session,
        *,
        override: AccountQuotaOverride,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        override.revoked_at = revoked_at
        override.revoked_by_user_id = revoked_by_user_id
        override.revocation_reason = reason
        db.flush()


entitlement_repository = EntitlementRepository()


__all__ = ["EntitlementRepository", "entitlement_repository"]
