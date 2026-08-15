from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.billing.infrastructure import application_gateway
from app.modules.billing.infrastructure.application_gateway import (
    SqlAlchemySubscriptionStore,
)


def _subscription(*, user_id: int, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        plan="researcher",
        stripe_customer_id="cus_fixture",
        stripe_subscription_id="sub_fixture",
        stripe_price_id="price_fixture",
        stripe_schedule_id=None,
        status=status,
        current_period_start=None,
        current_period_end=None,
        cancel_at_period_end=False,
    )


@pytest.mark.parametrize("existing", [False, True])
def test_subscription_save_locks_before_create_or_update_read(
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    db = MagicMock()
    user_id = 2**63 - 1
    events: list[str] = []
    current = _subscription(user_id=user_id, status="active") if existing else None
    updated = _subscription(user_id=user_id, status="canceled")

    def lock(_db: object, *, user_id: int) -> None:
        assert _db is db
        assert user_id == 2**63 - 1
        events.append("lock")

    def read(_db: object, requested_user_id: int) -> object | None:
        assert _db is db
        assert requested_user_id == user_id
        events.append("read")
        return current

    def write(
        _db: object,
        requested_user_id: int,
        changes: dict[str, object],
    ) -> object:
        assert _db is db
        assert requested_user_id == user_id
        assert changes == {"status": "canceled"}
        events.append("write")
        return updated

    monkeypatch.setattr(application_gateway, "lock_account_resource_quota", lock)
    monkeypatch.setattr(
        application_gateway.subscription_repository,
        "get_by_user_id",
        read,
    )
    monkeypatch.setattr(
        application_gateway.subscription_repository,
        "create_or_update",
        write,
    )

    result = SqlAlchemySubscriptionStore(db).save(user_id, status="canceled")

    assert result.changed is True
    assert result.record.status == "canceled"
    assert events == ["lock", "read", "write"]
