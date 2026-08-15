from unittest.mock import MagicMock, call, patch

from app.bootstrap.adapters.billing_capacity import BillingProjectCapacity


def test_project_creation_locks_account_before_capacity_read() -> None:
    db = MagicMock()
    actor = MagicMock(id=17)
    calls: list[str] = []

    with (
        patch(
            "app.bootstrap.adapters.billing_capacity.lock_account_resource_quota",
            side_effect=lambda *_args, **_kwargs: calls.append("lock"),
        ) as quota_lock,
        patch(
            "app.bootstrap.adapters.billing_capacity.can_user_create_project",
            side_effect=lambda *_args, **_kwargs: (
                calls.append("capacity") or (True, None)
            ),
        ),
    ):
        BillingProjectCapacity(db).require_create(actor=actor)

    assert calls == ["lock", "capacity"]
    assert quota_lock.call_args == call(db, user_id=17)
