from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.billing.application.entitlement_admin import (
    EntitlementAdmin,
    GrantRecord,
    OverrideRecord,
)
from app.shared.application import (
    Actor,
    CliOrigin,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError


@dataclass
class _Clock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class _Gateway:
    def __init__(self) -> None:
        self.grants: dict[int, GrantRecord] = {}
        self.overrides: dict[tuple[int, str], OverrideRecord] = {}
        self.locked: list[int] = []
        self.live_targets: dict[int, Actor] = {}
        self.reasons: list[str] = []

    def lock_account(self, *, user_id: int) -> None:
        self.locked.append(user_id)

    def lock_target_identity(self, *, user_id: int) -> Actor | None:
        return self.live_targets.get(user_id, _actor(user_id))

    def current_grant(self, *, user_id: int) -> GrantRecord | None:
        return self.grants.get(user_id)

    def create_grant(
        self,
        *,
        user_id: int,
        granted_by_user_id: int,
        granted_at: datetime,
        expires_at: datetime,
        reason: str,
    ) -> GrantRecord:
        del granted_by_user_id, granted_at
        self.reasons.append(reason)
        record = GrantRecord(uuid4(), user_id, expires_at)
        self.grants[user_id] = record
        return record

    def revoke_grant(
        self,
        *,
        grant_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        del revoked_by_user_id, revoked_at
        self.reasons.append(reason)
        user_id = next(
            user_id for user_id, grant in self.grants.items() if grant.id == grant_id
        )
        del self.grants[user_id]

    def current_override(
        self, *, user_id: int, resource_key: str
    ) -> OverrideRecord | None:
        return self.overrides.get((user_id, resource_key))

    def create_override(
        self,
        *,
        user_id: int,
        resource_key: str,
        limit_value: int,
        set_by_user_id: int,
        set_at: datetime,
        expires_at: datetime,
        reason: str,
    ) -> OverrideRecord:
        del set_by_user_id, set_at
        self.reasons.append(reason)
        record = OverrideRecord(uuid4(), user_id, resource_key, limit_value, expires_at)
        self.overrides[(user_id, resource_key)] = record
        return record

    def revoke_override(
        self,
        *,
        override_id: UUID,
        revoked_by_user_id: int,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        del revoked_by_user_id, revoked_at
        self.reasons.append(reason)
        key = next(
            key
            for key, override in self.overrides.items()
            if override.id == override_id
        )
        del self.overrides[key]


class _Journal:
    def __init__(self) -> None:
        self.entries: list[object] = []

    def append(self, **entry: object) -> None:
        self.entries.append(entry)


def _actor(user_id: int, *, admin: bool = False, verified: bool = True) -> Actor:
    return Actor(
        id=user_id,
        email=f"user-{user_id}@example.com",
        display_name=None,
        status="active",
        email_verified=verified,
        is_admin=admin,
    )


def _operation() -> object:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=CliOrigin("entitlements.grant-researcher", uuid4()),
        credential=None,
    )


def test_researcher_grant_is_365_days_and_repeated_call_is_unchanged() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    gateway = _Gateway()
    journal = _Journal()
    clock = _Clock(now)
    service = EntitlementAdmin(gateway, journal=journal, clock=clock)  # type: ignore[arg-type]

    first = service.grant_researcher(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=(_actor(2),),
        days=365,
        reason="team testing",
    )
    clock.current += timedelta(seconds=5)
    repeated = service.grant_researcher(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=(_actor(2),),
        days=365,
        reason="team testing",
    )

    assert first[0].changed is True
    assert gateway.grants[2].expires_at == now + timedelta(days=365)
    assert repeated[0].changed is False
    assert len(journal.entries) == 1
    assert gateway.reasons == ["team testing"]


def test_one_day_grant_near_expiry_is_extended() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    gateway = _Gateway()
    clock = _Clock(now)
    service = EntitlementAdmin(
        gateway,
        journal=_Journal(),  # type: ignore[arg-type]
        clock=clock,
    )

    first = service.grant_researcher(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=(_actor(2),),
        days=1,
        reason="short test grant",
    )
    clock.current += timedelta(hours=23, minutes=59)
    extended = service.grant_researcher(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=(_actor(2),),
        days=1,
        reason="extend short test grant",
    )

    assert first[0].changed is True
    assert extended[0].changed is True
    assert extended[0].resource_id != first[0].resource_id
    assert gateway.grants[2].expires_at == clock.current + timedelta(days=1)


def test_batch_targets_are_all_validated_before_any_mutation() -> None:
    gateway = _Gateway()
    gateway.live_targets[3] = _actor(3, verified=False)
    service = EntitlementAdmin(
        gateway,
        journal=_Journal(),  # type: ignore[arg-type]
        clock=_Clock(datetime(2026, 8, 16, tzinfo=UTC)),
    )

    with pytest.raises(AppError) as error:
        service.grant_researcher(
            actor=_actor(1, admin=True),
            operation=_operation(),  # type: ignore[arg-type]
            targets=(_actor(2), _actor(3, verified=False)),
            days=365,
            reason="batch test",
        )

    assert error.value.code == "entitlement_target_ineligible"
    assert gateway.grants == {}
    assert gateway.locked == [2, 3]


def test_zero_quota_override_is_valid_and_can_be_cleared() -> None:
    gateway = _Gateway()
    journal = _Journal()
    service = EntitlementAdmin(
        gateway,
        journal=journal,  # type: ignore[arg-type]
        clock=_Clock(datetime(2026, 8, 16, tzinfo=UTC)),
    )
    target = _actor(2)

    created = service.set_quota(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        target=target,
        resource_key="paper_uploads",
        limit_value=0,
        days=30,
        reason="boundary test",
    )
    cleared = service.clear_quota(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        target=target,
        resource_key="paper_uploads",
        reason="boundary complete",
    )

    assert created.changed is True
    assert cleared.changed is True
    assert gateway.overrides == {}
    assert len(journal.entries) == 2


def test_quota_override_retries_are_tolerated_but_near_expiry_is_extended() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    gateway = _Gateway()
    clock = _Clock(now)
    service = EntitlementAdmin(
        gateway,
        journal=_Journal(),  # type: ignore[arg-type]
        clock=clock,
    )
    target = _actor(2)

    first = service.set_quota(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        target=target,
        resource_key="projects",
        limit_value=1,
        days=1,
        reason="short boundary",
    )
    clock.current += timedelta(seconds=5)
    retry = service.set_quota(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        target=target,
        resource_key="projects",
        limit_value=1,
        days=1,
        reason="short boundary",
    )
    clock.current += timedelta(hours=23, minutes=59)
    extended = service.set_quota(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        target=target,
        resource_key="projects",
        limit_value=1,
        days=1,
        reason="extend short boundary",
    )

    assert first.changed is True
    assert retry.changed is False
    assert retry.resource_id == first.resource_id
    assert extended.changed is True
    assert extended.resource_id != first.resource_id


def test_researcher_revoke_batch_is_atomic_shape_and_idempotent() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    gateway = _Gateway()
    service = EntitlementAdmin(
        gateway,
        journal=_Journal(),  # type: ignore[arg-type]
        clock=_Clock(now),
    )
    targets = (_actor(2), _actor(3))
    service.grant_researcher(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=targets,
        days=365,
        reason="batch grant",
    )

    revoked = service.revoke_researcher_batch(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=targets,
        reason="batch revoke",
    )
    repeated = service.revoke_researcher_batch(
        actor=_actor(1, admin=True),
        operation=_operation(),  # type: ignore[arg-type]
        targets=targets,
        reason="batch revoke",
    )

    assert [result.changed for result in revoked] == [True, True]
    assert [result.changed for result in repeated] == [False, False]
