"""SQLAlchemy adapter for Scholens identity/profile use cases."""

from app.modules.identity.application.identity import (
    AdminStatusResolution,
    AuthenticatedIdentity,
    BlockedStatusResolution,
    IdentityProfile,
    IdentityProfileResolution,
    LocalIdentity,
)
from app.modules.identity.infrastructure.users import user_repository
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
