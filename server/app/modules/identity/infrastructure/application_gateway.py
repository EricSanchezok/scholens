"""SQLAlchemy adapter for Scholens identity/profile use cases."""

from app.modules.identity.application.identity import (
    AdminStatusResolution,
    AuthenticatedIdentity,
    BlockedStatusResolution,
    IdentityProfile,
    IdentityProfileResolution,
    LockedIdentity,
    LocalIdentity,
)
from app.modules.identity.infrastructure.models import AuthUser, UserProfile
from app.modules.identity.infrastructure.users import user_repository
from app.shared.application import Actor
from sqlalchemy import func, select
from sqlalchemy.orm import Session


# Stable two-key PostgreSQL advisory-lock namespace: ASCII "SCHO" / "ADMI".
# Every transaction that can create the first or remove an available admin
# serializes through this roster lock before re-reading the invariant.
ADMIN_ROSTER_LOCK_NAMESPACE = (0x5343484F, 0x41444D49)


class SqlAlchemyIdentityGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve_profile(self, *, user_id: int) -> IdentityProfileResolution:
        profile, created = user_repository.resolve_profile(
            self._db,
            user_id=user_id,
        )
        return IdentityProfileResolution(
            profile=IdentityProfile(
                locale=profile.locale,
                is_admin=profile.is_admin,
                is_blocked=profile.is_blocked,
            ),
            created=created,
        )

    def local_identity(self, *, user_id: int) -> LocalIdentity | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None or user.profile is None:
            return None
        return LocalIdentity(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=str(user.status),
            email_verified=user.email_verified_at is not None,
            profile=IdentityProfile(
                locale=user.profile.locale,
                is_admin=user.profile.is_admin,
                is_blocked=user.profile.is_blocked,
            ),
        )

    def authenticated_identity(
        self,
        *,
        user_id: int,
    ) -> AuthenticatedIdentity | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None:
            return None
        return AuthenticatedIdentity(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=str(user.status),
            email_verified=user.email_verified_at is not None,
        )

    def available_admin_count(self) -> int:
        return user_repository.available_admin_count(self._db)

    def lock_admin_roster(self) -> None:
        self._db.execute(
            select(func.pg_advisory_xact_lock(*ADMIN_ROSTER_LOCK_NAMESPACE))
        )

    def lock_identity(self, *, user_id: int) -> LockedIdentity | None:
        user = self._db.scalar(
            select(AuthUser).where(AuthUser.id == user_id).with_for_update()
        )
        if user is None:
            return None
        profile = self._db.scalar(
            select(UserProfile).where(UserProfile.user_id == user_id).with_for_update()
        )
        return LockedIdentity(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=str(user.status),
            email_verified=user.email_verified_at is not None,
            profile=(
                IdentityProfile(
                    locale=profile.locale,
                    is_admin=profile.is_admin,
                    is_blocked=profile.is_blocked,
                )
                if profile is not None
                else None
            ),
        )

    def lock_actor_identity(self, *, user_id: int) -> Actor | None:
        identity = self.lock_identity(user_id=user_id)
        if identity is None:
            return None
        profile = identity.profile
        return Actor.from_identity_projection(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            locale=profile.locale if profile else None,
            is_admin=profile.is_admin if profile else False,
            is_blocked=profile.is_blocked if profile else False,
        )

    def set_blocked(
        self,
        *,
        user_id: int,
        blocked: bool,
    ) -> BlockedStatusResolution | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None:
            return None
        profile, profile_created = user_repository.resolve_profile(
            self._db,
            user_id=user_id,
        )
        changed = user_repository.set_blocked(
            self._db,
            profile=profile,
            blocked=blocked,
        )
        return BlockedStatusResolution(
            profile_created=profile_created,
            changed=changed,
        )

    def set_admin(
        self,
        *,
        user_id: int,
        enabled: bool,
    ) -> AdminStatusResolution | None:
        user = user_repository.get(self._db, id=user_id)
        if user is None:
            return None
        profile, profile_created = user_repository.resolve_profile(
            self._db,
            user_id=user_id,
        )
        changed = user_repository.set_admin(
            self._db,
            profile=profile,
            enabled=enabled,
        )
        return AdminStatusResolution(
            profile_created=profile_created,
            changed=changed,
        )
