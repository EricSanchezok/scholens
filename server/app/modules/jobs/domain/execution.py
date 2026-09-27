"""Recovery bounds for explicitly fenced operations; legacy policy is unchanged."""

from datetime import datetime, timedelta

MAX_EXECUTION_ATTEMPTS = 4
MAX_EXECUTION_RECOVERY_AGE = timedelta(hours=2)


def execution_exhausted(
    *, attempts: int, started_at: datetime | None, now: datetime
) -> bool:
    return attempts >= MAX_EXECUTION_ATTEMPTS or (
        started_at is not None and now - started_at >= MAX_EXECUTION_RECOVERY_AGE
    )
