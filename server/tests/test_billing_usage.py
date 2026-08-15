from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.billing.application.contracts import UsagePeriod
from app.modules.billing.infrastructure import quotas
from app.modules.billing.domain import resolve_entitlements
from app.shared.application import Actor


class _UsageDatabase:
    def __init__(self, *, token_usage: int) -> None:
        self._values = iter((2, token_usage))

    def scalar(self, _statement: object) -> int:
        return next(self._values)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


@pytest.mark.parametrize(
    ("period", "weeks", "start"),
    [
        (UsagePeriod.CURRENT_WEEK, 1, date(2026, 8, 10)),
        (UsagePeriod.FOUR_WEEKS, 4, date(2026, 7, 20)),
        (UsagePeriod.TWELVE_WEEKS, 12, date(2026, 5, 25)),
    ],
)
def test_usage_period_aggregates_monday_aligned_token_windows(
    monkeypatch: pytest.MonkeyPatch,
    period: UsagePeriod,
    weeks: int,
    start: date,
) -> None:
    monkeypatch.setattr(
        quotas,
        "get_user_entitlements",
        lambda _db, _actor: resolve_entitlements(
            None,
            now=datetime.now(UTC),
        ),
    )
    monkeypatch.setattr(
        quotas.resource_usage_repository,
        "completed_reference_count",
        lambda _db, *, user_id: 3,
    )
    monkeypatch.setattr(
        quotas.resource_usage_repository,
        "completed_storage_kb",
        lambda _db, *, user_id: 1_024,
    )
    monkeypatch.setattr(
        "app.llm.token_credits.utc_week_start",
        lambda: date(2026, 8, 10),
    )

    response = quotas.get_user_usage_info(
        _UsageDatabase(token_usage=4_000_000 * weeks),  # type: ignore[arg-type]
        _actor(),
        period,
    )

    assert response["period"] == period.value
    assert response["period_start"] == start
    assert response["period_end"] == date(2026, 8, 16)
    limits = response["limits"]
    assert isinstance(limits, dict)
    assert limits["knowledge_base_size_kb"] == 5 * 1024 * 1024
    assert "knowledge_base_size" not in limits
    usage = response["usage"]
    assert isinstance(usage, dict)
    assert usage["knowledge_base_size_kb"] == 1_024
    assert usage["knowledge_base_size_remaining_kb"] == 5 * 1024 * 1024 - 1_024
    assert "knowledge_base_size" not in usage
    assert usage["token_credits_limit"] == 30_000_000 * weeks
    assert usage["token_credits_used"] == 4_000_000 * weeks
    assert usage["token_credits_remaining"] == 26_000_000 * weeks
    assert usage["token_credits_overage"] == 0
