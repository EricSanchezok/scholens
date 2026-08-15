from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.identity.application.identity import (
    Identity,
    IdentityProfile,
    LocalIdentity,
)
from app.modules.identity.application.contracts import SetUserBlockedRequest
from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError


def _admin() -> Actor:
    return Actor(
        id=1,
        email="admin@example.com",
        display_name=None,
        status="active",
        email_verified=True,
        is_admin=True,
    )


def _operation() -> object:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=CliOrigin("users.revoke-admin", uuid4()),
        credential=None,
    )


def test_final_available_admin_cannot_be_revoked_or_blocked() -> None:
    gateway = MagicMock()
    gateway.available_admin_count.return_value = 1
    gateway.authenticated_identity.return_value = MagicMock(
        id=2,
        status="active",
        email_verified=True,
    )
    gateway.local_identity.return_value = LocalIdentity(
        id=2,
        email="last@example.com",
        display_name=None,
        status="active",
        email_verified=True,
        profile=IdentityProfile(locale=None, is_admin=True, is_blocked=False),
    )
    service = Identity(gateway, journal=MagicMock())

    with pytest.raises(AppError) as revoke_error:
        service.set_admin(
            actor=_admin(),
            operation=_operation(),  # type: ignore[arg-type]
            user_id=2,
            enabled=False,
        )

    assert revoke_error.value.code == "last_admin_required"
    with pytest.raises(AppError) as block_error:
        service.set_blocked(
            actor=_admin(),
            operation=_operation(),  # type: ignore[arg-type]
            user_id=2,
            request=SetUserBlockedRequest(blocked=True),
        )

    assert block_error.value.code == "last_admin_required"
    gateway.set_admin.assert_not_called()
    gateway.set_blocked.assert_not_called()


def test_bootstrap_admin_closes_after_the_first_available_admin() -> None:
    gateway = MagicMock()
    gateway.available_admin_count.return_value = 1
    service = Identity(gateway, journal=MagicMock())

    with pytest.raises(AppError) as error:
        service.bootstrap_admin(
            operation=_operation(),  # type: ignore[arg-type]
            user_id=2,
        )

    assert error.value.code == "admin_bootstrap_closed"
    gateway.set_admin.assert_not_called()
