"""Billing-owned PostgreSQL lock namespace for account entitlement and quota writes."""

import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# One-key PostgreSQL advisory locks occupy a key space distinct from two-key
# locks. This versioned domain separator preserves the entire auth bigint ID
# range without sharing raw IDs with unrelated one-key lock users. A theoretical
# 64-bit hash collision only adds conservative serialization.
ACCOUNT_QUOTA_LOCK_NAMESPACE = b"scholens.billing.account-resource-quota.v1"
POSTGRES_BIGINT_MIN = -(2**63)
POSTGRES_BIGINT_MAX = 2**63 - 1


def account_quota_lock_key(user_id: int) -> int:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or not POSTGRES_BIGINT_MIN <= user_id <= POSTGRES_BIGINT_MAX
    ):
        raise ValueError("Account quota lock user_id must fit PostgreSQL bigint")
    digest = hashlib.blake2b(
        ACCOUNT_QUOTA_LOCK_NAMESPACE + b"\0" + str(user_id).encode("ascii"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def lock_account_resource_quota(db: Session, *, user_id: int) -> None:
    """Serialize entitlement and resource-capacity writes for one account."""
    db.execute(select(func.pg_advisory_xact_lock(account_quota_lock_key(user_id))))


__all__ = [
    "ACCOUNT_QUOTA_LOCK_NAMESPACE",
    "account_quota_lock_key",
    "lock_account_resource_quota",
]
