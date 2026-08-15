from __future__ import annotations

from app.modules.identity.infrastructure.models import AuthUser, UserProfile
from app.shared.application import Actor
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload


class UserRepository:
    """Read shared identities and manage Scholens-only profile state."""

    def get(self, db: Session, *, id: int) -> AuthUser | None:
        return db.scalars(
            select(AuthUser)
            .options(joinedload(AuthUser.profile))
            .where(AuthUser.id == id)
        ).first()

    def get_by_email(self, db: Session, *, email: str) -> AuthUser | None:
        return db.scalars(
            select(AuthUser)
            .options(joinedload(AuthUser.profile))
            .where(AuthUser.email == email.lower().strip())
        ).first()

    def resolve_profile(
        self,
        db: Session,
        *,
        user_id: int,
    ) -> tuple[UserProfile, bool]:
        profile = db.scalars(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).first()
        if profile is not None:
            return profile, False

        created_user_id = db.scalar(
            insert(UserProfile)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=[UserProfile.user_id])
            .returning(UserProfile.user_id)
        )
        db.flush()
        return (
            db.scalars(select(UserProfile).where(UserProfile.user_id == user_id)).one(),
            created_user_id is not None,
        )

    def set_blocked(
        self,
        db: Session,
        *,
        profile: UserProfile,
        blocked: bool,
    ) -> bool:
        if profile.is_blocked == blocked:
            return False
        profile.is_blocked = blocked
        db.flush()
        return True

    def set_admin(
        self,
        db: Session,
        *,
        profile: UserProfile,
        enabled: bool,
    ) -> bool:
        if profile.is_admin == enabled:
            return False
        profile.is_admin = enabled
        db.flush()
        return True

    def available_admin_count(self, db: Session) -> int:
        return int(
            db.scalar(
                select(func.count(UserProfile.user_id))
                .join(AuthUser, AuthUser.id == UserProfile.user_id)
                .where(
                    UserProfile.is_admin.is_(True),
                    UserProfile.is_blocked.is_(False),
                    AuthUser.status == "active",
                    AuthUser.email_verified_at.is_not(None),
                )
            )
            or 0
        )


user_repository = UserRepository()


def actor_from_auth_user(user: AuthUser) -> Actor:
    """Map the shared auth projection into a transport-neutral caller."""
    profile = user.profile
    return Actor.from_identity_projection(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=str(user.status),
        email_verified=user.email_verified_at is not None,
        locale=profile.locale if profile else None,
        is_admin=profile.is_admin if profile else False,
        is_blocked=profile.is_blocked if profile else False,
    )
