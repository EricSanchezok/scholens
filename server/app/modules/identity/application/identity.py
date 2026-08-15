"""Scholens identity/profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.identity.application.contracts import (
    SetUserAdminResponse,
    SetUserBlockedRequest,
    SetUserBlockedResponse,
)
from app.modules.identity.domain import (
    AccountAccessFacts,
    require_administrator,
    require_product_access,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind

IDENTITY_PROFILE_CREATED = OperationAction("identity.profile_created")
IDENTITY_ACCOUNT_BLOCKED = OperationAction("identity.account_blocked")
IDENTITY_ACCOUNT_UNBLOCKED = OperationAction("identity.account_unblocked")
IDENTITY_ADMIN_GRANTED = OperationAction("identity.admin_granted")
IDENTITY_ADMIN_REVOKED = OperationAction("identity.admin_revoked")


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    id: int
    email: str
    display_name: str | None
    status: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    locale: str | None
    is_admin: bool
    is_blocked: bool


@dataclass(frozen=True, slots=True)
class IdentityProfileResolution:
    profile: IdentityProfile
    created: bool


@dataclass(frozen=True, slots=True)
class LocalIdentity:
    id: int
    email: str
    display_name: str | None
    status: str
    email_verified: bool
    profile: IdentityProfile


@dataclass(frozen=True, slots=True)
class BlockedStatusResolution:
    profile_created: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class AdminStatusResolution:
    profile_created: bool
    changed: bool


class IdentityGateway(Protocol):
    def resolve_profile(self, *, user_id: int) -> IdentityProfileResolution: ...

    def local_identity(self, *, user_id: int) -> LocalIdentity | None: ...

    def authenticated_identity(
        self,
        *,
        user_id: int,
    ) -> AuthenticatedIdentity | None: ...

    def available_admin_count(self) -> int: ...

    def lock_admin_roster(self) -> None: ...

    def set_blocked(
        self,
        *,
        user_id: int,
        blocked: bool,
    ) -> BlockedStatusResolution | None: ...

    def set_admin(
        self,
        *,
        user_id: int,
        enabled: bool,
    ) -> AdminStatusResolution | None: ...


class Identity:
    def __init__(
        self,
        gateway: IdentityGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def resolve_actor(
        self,
        identity: AuthenticatedIdentity,
        *,
        operation: OperationContext,
    ) -> Actor:
        resolution = self._gateway.resolve_profile(user_id=identity.id)
        actor = self._actor(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            profile=resolution.profile,
        )
        if resolution.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_PROFILE_CREATED,
                resources=(ResourceRef("user", str(actor.id)),),
            )
        return actor

    def bootstrap_profile(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        identity: AuthenticatedIdentity,
    ) -> tuple[Actor, bool]:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        if identity.status != "active" or not identity.email_verified:
            raise AppError(
                code="profile_target_ineligible",
                message="The account must be active and email verified",
                kind=FailureKind.CONFLICT,
            )
        resolution = self._gateway.resolve_profile(user_id=identity.id)
        target = self._actor(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            profile=resolution.profile,
        )
        if resolution.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_PROFILE_CREATED,
                resources=(ResourceRef("user", str(target.id)),),
            )
        return target, resolution.created

    def resolve_actor_by_user_id(self, user_id: int) -> Actor:
        identity = self._gateway.local_identity(user_id=user_id)
        if identity is None:
            raise AppError(
                code="identity_profile_incomplete",
                message="The local identity profile is unavailable",
                kind=FailureKind.NOT_FOUND,
            )
        return self._actor(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            profile=identity.profile,
        )

    @staticmethod
    def _actor(
        *,
        user_id: int,
        email: str,
        display_name: str | None,
        status: str,
        email_verified: bool,
        profile: IdentityProfile,
    ) -> Actor:
        facts = AccountAccessFacts(
            status=status,
            is_blocked=profile.is_blocked,
            is_admin=profile.is_admin,
        )
        require_product_access(facts)
        return Actor(
            id=user_id,
            email=email,
            display_name=display_name,
            status=status,
            email_verified=email_verified,
            locale=profile.locale,
            is_admin=profile.is_admin,
            is_blocked=profile.is_blocked,
            is_active=facts.is_active,
        )

    def set_blocked(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        user_id: int,
        request: SetUserBlockedRequest,
    ) -> SetUserBlockedResponse:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        if request.blocked and user_id == actor.id:
            raise AppError(
                code="admin_self_block_forbidden",
                message="An administrator cannot block their own account",
                kind=FailureKind.CONFLICT,
            )
        if request.blocked:
            self._gateway.lock_admin_roster()
        target_identity = self._gateway.local_identity(user_id=user_id)
        if (
            request.blocked
            and target_identity is not None
            and target_identity.profile.is_admin
            and target_identity.email_verified
            and self._gateway.available_admin_count() <= 1
        ):
            raise AppError(
                code="last_admin_required",
                message="The final available administrator cannot be blocked",
                kind=FailureKind.CONFLICT,
            )
        resolution = self._gateway.set_blocked(
            user_id=user_id,
            blocked=request.blocked,
        )
        if resolution is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                kind=FailureKind.NOT_FOUND,
            )
        target = ResourceRef("user", str(user_id))
        if resolution.profile_created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_PROFILE_CREATED,
                resources=(target,),
            )
        if resolution.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=(
                    IDENTITY_ACCOUNT_BLOCKED
                    if request.blocked
                    else IDENTITY_ACCOUNT_UNBLOCKED
                ),
                resources=(target,),
            )
        action = "blocked" if request.blocked else "unblocked"
        response = SetUserBlockedResponse(
            success=True,
            message=f"User {action} successfully",
        )
        response._changed = resolution.changed
        return response

    def bootstrap_admin(
        self,
        *,
        operation: OperationContext,
        user_id: int,
    ) -> SetUserAdminResponse:
        self._gateway.lock_admin_roster()
        if self._gateway.available_admin_count() != 0:
            raise AppError(
                code="admin_bootstrap_closed",
                message="Administrator bootstrap is available only before the first admin",
                kind=FailureKind.CONFLICT,
            )
        identity = self._gateway.authenticated_identity(user_id=user_id)
        if (
            identity is None
            or identity.status != "active"
            or not identity.email_verified
        ):
            raise AppError(
                code="admin_target_ineligible",
                message="The first administrator must be active and email verified",
                kind=FailureKind.CONFLICT,
            )
        resolution = self._gateway.set_admin(user_id=user_id, enabled=True)
        if resolution is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                kind=FailureKind.NOT_FOUND,
            )
        target = ResourceRef("user", str(user_id))
        if resolution.profile_created:
            self._journal.append(
                actor=None,
                operation=operation,
                action=IDENTITY_PROFILE_CREATED,
                resources=(target,),
            )
        if resolution.changed:
            self._journal.append(
                actor=None,
                operation=operation,
                action=IDENTITY_ADMIN_GRANTED,
                resources=(target,),
            )
        return SetUserAdminResponse(
            success=True,
            changed=resolution.changed,
            message="Administrator bootstrapped",
        )

    def set_admin(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        user_id: int,
        enabled: bool,
    ) -> SetUserAdminResponse:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        if not enabled:
            self._gateway.lock_admin_roster()
        identity = self._gateway.authenticated_identity(user_id=user_id)
        if identity is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                kind=FailureKind.NOT_FOUND,
            )
        if enabled and (identity.status != "active" or not identity.email_verified):
            raise AppError(
                code="admin_target_ineligible",
                message="Administrators must be active and email verified",
                kind=FailureKind.CONFLICT,
            )
        current = self._gateway.local_identity(user_id=user_id)
        if (
            not enabled
            and current is not None
            and current.profile.is_admin
            and not current.profile.is_blocked
            and current.status == "active"
            and current.email_verified
            and self._gateway.available_admin_count() <= 1
        ):
            raise AppError(
                code="last_admin_required",
                message="The final available administrator cannot be revoked",
                kind=FailureKind.CONFLICT,
            )
        resolution = self._gateway.set_admin(user_id=user_id, enabled=enabled)
        if resolution is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                kind=FailureKind.NOT_FOUND,
            )
        target = ResourceRef("user", str(user_id))
        if resolution.profile_created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_PROFILE_CREATED,
                resources=(target,),
            )
        if resolution.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=IDENTITY_ADMIN_GRANTED if enabled else IDENTITY_ADMIN_REVOKED,
                resources=(target,),
            )
        verb = "granted" if enabled else "revoked"
        return SetUserAdminResponse(
            success=True,
            changed=resolution.changed,
            message=f"Administrator access {verb}",
        )
