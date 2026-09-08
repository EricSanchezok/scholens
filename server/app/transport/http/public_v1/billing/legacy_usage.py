"""Retired v1 meters retained only for previously released clients.

Owner: Scholens platform. Remove after the usage endpoint's registered retirement.
The zero token fields do not record or enforce model usage; project capacity is
unbounded and represented by a legacy signed-bigint ceiling.
"""

from datetime import UTC, date, datetime, timedelta
from pydantic import BaseModel
from app.modules.billing.application.contracts import (
    CapacityLimits,
    CapacityUsage,
    CapacityResponse,
    UsagePeriod,
)


class SubscriptionLimits(CapacityLimits):
    token_credits_weekly: int
    project_papers: int


class SubscriptionUsage(CapacityUsage):
    token_credits_limit: int
    token_credits_used: int
    token_credits_remaining: int
    token_credits_overage: int


class UsageResponse(BaseModel):
    plan: str
    period: UsagePeriod
    period_start: date
    period_end: date
    limits: SubscriptionLimits
    usage: SubscriptionUsage

    @classmethod
    def from_capacity(
        cls, value: CapacityResponse, period: UsagePeriod
    ) -> "UsageResponse":
        today = datetime.now(UTC).date()
        start = today - timedelta(days=today.weekday())
        return cls(
            plan=value.plan,
            period=period,
            period_start=start - timedelta(weeks=period.weeks - 1),
            period_end=start + timedelta(days=6),
            limits=SubscriptionLimits(
                **value.limits.model_dump(),
                token_credits_weekly=0,
                project_papers=2**63 - 1,
            ),
            usage=SubscriptionUsage(
                **value.usage.model_dump(),
                token_credits_limit=0,
                token_credits_used=0,
                token_credits_remaining=0,
                token_credits_overage=0,
            ),
        )
