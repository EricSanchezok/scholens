"""Billing quota boundary used by Zotero import planning."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.database.models import SubscriptionPlan
from app.modules.billing.infrastructure.quotas import (
    get_remaining_paper_upload_slots,
)
from app.modules.billing.domain import entitlements_for


@pytest.mark.parametrize(
    ("plan", "used", "expected"),
    [
        (SubscriptionPlan.BASIC, 299, 1),
        (SubscriptionPlan.BASIC, 300, 0),
        (SubscriptionPlan.BASIC, 315, 0),
        (SubscriptionPlan.RESEARCHER, 4_999, 1),
        (SubscriptionPlan.RESEARCHER, 5_000, 0),
    ],
)
def test_remaining_paper_upload_slots(
    plan: str,
    used: int,
    expected: int,
) -> None:
    actor = MagicMock(id=7)
    with (
        patch(
            "app.modules.billing.infrastructure.quotas.get_user_entitlements",
            return_value=SimpleNamespace(limits=entitlements_for(plan)),
        ),
        patch(
            "app.modules.billing.infrastructure.quotas.resource_usage_repository"
        ) as usage,
    ):
        usage.completed_reference_count.return_value = used
        assert get_remaining_paper_upload_slots(MagicMock(), actor) == expected
