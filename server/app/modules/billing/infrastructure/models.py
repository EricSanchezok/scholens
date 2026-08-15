from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    func,
    Integer,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import (
    SubscriptionPlan,
    SubscriptionStatus,
    StripeWebhookEventStatus,
)

if TYPE_CHECKING:
    from app.modules.identity.infrastructure.models import AuthUser


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Subscription details
    plan: Mapped[str] = mapped_column(
        String, nullable=False, default=SubscriptionPlan.BASIC
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=SubscriptionStatus.ACTIVE
    )

    # Billing period
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Stripe integration fields
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Cancel at period end flag
    cancel_at_period_end: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Stripe Subscription Schedule ID (for deferred interval changes)
    stripe_schedule_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # When the subscription was canceled, if it was
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="subscription")


class AccountPlanGrant(Base):
    """Time-bounded product entitlement independent of payment state."""

    __tablename__ = "account_plan_grants"
    __table_args__ = (
        CheckConstraint("plan = 'researcher'", name="ck_account_plan_grants_plan"),
        CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_account_plan_grants_reason",
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR "
            "length(btrim(revocation_reason)) BETWEEN 1 AND 500",
            name="ck_account_plan_grants_revocation_reason",
        ),
        CheckConstraint(
            "expires_at > created_at AND "
            "expires_at <= created_at + interval '365 days'",
            name="ck_account_plan_grants_duration",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_account_plan_grants_revocation_state",
        ),
        Index(
            "uq_account_plan_grants_unrevoked_user",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    granted_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AccountQuotaOverride(Base):
    """One expiring replacement for one numerical entitlement."""

    __tablename__ = "account_quota_overrides"
    __table_args__ = (
        CheckConstraint(
            "resource_key IN ('paper_uploads', 'knowledge_base_size_kb', "
            "'token_credits_weekly', 'projects', 'project_papers')",
            name="ck_account_quota_overrides_resource",
        ),
        CheckConstraint("limit_value >= 0", name="ck_account_quota_overrides_value"),
        CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 500",
            name="ck_account_quota_overrides_reason",
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR "
            "length(btrim(revocation_reason)) BETWEEN 1 AND 500",
            name="ck_account_quota_overrides_revocation_reason",
        ),
        CheckConstraint(
            "expires_at > created_at AND "
            "expires_at <= created_at + interval '365 days'",
            name="ck_account_quota_overrides_duration",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_account_quota_overrides_revocation_state",
        ),
        Index(
            "uq_account_quota_overrides_unrevoked_resource",
            "user_id",
            "resource_key",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_key: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    set_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StripeWebhookEvent(Base):
    """Minimal, non-PII ledger for reliable Stripe webhook processing."""

    __tablename__ = "stripe_webhook_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=StripeWebhookEventStatus.PROCESSING,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'ignored')",
            name="ck_stripe_webhook_events_status",
        ),
    )
