"""Billing-owned PostgreSQL lock namespace for account entitlement and quota writes."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Two-key PostgreSQL advisory namespace: ASCII "BILL" plus the auth user ID.
# Keeping the resource type in the first int32 key prevents accidental
# collisions with unrelated global locks while preserving one shared lock for
# entitlement changes and every account-capacity mutation.
ACCOUNT_QUOTA_LOCK_NAMESPACE = 0x42494C4C
POSTGRES_INT32_MIN = -(2**31)
POSTGRES_INT32_MAX = 2**31 - 1


def account_quota_lock_key(user_id: int) -> tuple[int, int]:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or not POSTGRES_INT32_MIN <= user_id <= POSTGRES_INT32_MAX
    ):
        raise ValueError("Account quota lock user_id must fit PostgreSQL int32")
    return ACCOUNT_QUOTA_LOCK_NAMESPACE, user_id


def lock_account_resource_quota(db: Session, *, user_id: int) -> None:
    """Serialize entitlement and resource-capacity writes for one account."""
    db.execute(select(func.pg_advisory_xact_lock(*account_quota_lock_key(user_id))))


__all__ = [
    "ACCOUNT_QUOTA_LOCK_NAMESPACE",
    "account_quota_lock_key",
    "lock_account_resource_quota",
]
