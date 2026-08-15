from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.billing.infrastructure import quotas
from app.modules.billing.infrastructure.account_locks import (
    ACCOUNT_QUOTA_LOCK_NAMESPACE,
    account_quota_lock_key,
)
from app.modules.billing.infrastructure.entitlement_admin_gateway import (
    SqlAlchemyEntitlementAdminGateway,
)


def _compiled_lock(db: MagicMock) -> str:
    statement = db.execute.call_args.args[0]
    return " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )


def test_quota_and_entitlement_paths_share_the_billing_lock_namespace() -> None:
    quota_db = MagicMock()
    entitlement_db = MagicMock()

    quotas.lock_account_resource_quota(quota_db, user_id=17)
    SqlAlchemyEntitlementAdminGateway(
        entitlement_db,
        lock_target_identity=MagicMock(),
    ).lock_account(user_id=17)

    assert account_quota_lock_key(17) == (ACCOUNT_QUOTA_LOCK_NAMESPACE, 17)
    assert _compiled_lock(quota_db) == _compiled_lock(entitlement_db)
    assert _compiled_lock(quota_db) == (
        "SELECT pg_advisory_xact_lock(1112099916, 17) AS pg_advisory_xact_lock_1"
    )


@pytest.mark.parametrize("user_id", [True, -(2**31) - 1, 2**31])
def test_account_quota_lock_rejects_non_int32_user_ids(user_id: object) -> None:
    with pytest.raises(ValueError, match="must fit PostgreSQL int32"):
        account_quota_lock_key(user_id)  # type: ignore[arg-type]
