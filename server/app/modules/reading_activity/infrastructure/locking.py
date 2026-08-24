"""Transaction locks shared by preference, ingest, and erasure boundaries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def lock_user_activity(db: Session, *, user_id: int) -> None:
    """Serialize user-wide policy changes, new sessions, and scoped erasure."""

    key = f"reading-activity-user:{user_id}"
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


__all__ = ["lock_user_activity"]
