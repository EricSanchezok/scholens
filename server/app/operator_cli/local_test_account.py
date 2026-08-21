"""Identity-owned fixture seeding for the guarded local-development CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sanchezcloud_identity import (
    AsyncpgUserDatabase,
    AuthConfig,
    UserManager,
    close_pool,
    create_pool,
)
from sanchezcloud_identity.models.user import UserRecord
from sanchezcloud_identity.password import verify_password
from sqlalchemy.engine import make_url


class LocalIdentityDatabase(Protocol):
    async def get_user_by_email(self, email: str) -> UserRecord | None: ...

    async def reset_failed_login_attempts(self, user_id: int) -> None: ...


class LocalIdentityManager(Protocol):
    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> None: ...

    async def resend_verification(self, email: str) -> bool: ...

    async def verify_email(self, token: str) -> bool: ...

    async def forgot_password(self, email: str) -> bool: ...

    async def reset_password(self, token: str, new_password: str) -> bool: ...

    async def update_profile(
        self,
        user_id: int,
        display_name: str | None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class LocalTestIdentityResult:
    user_id: int
    email: str
    created: bool
    password_changed: bool
    profile_changed: bool
    verified: bool

    @property
    def changed(self) -> bool:
        return self.created or self.password_changed or self.profile_changed


def _valid_token(token: str | None, expires_at: datetime | None) -> bool:
    if token is None or expires_at is None:
        return False
    now = datetime.now(UTC)
    normalized_expiry = (
        expires_at.replace(tzinfo=UTC)
        if expires_at.tzinfo is None
        else expires_at.astimezone(UTC)
    )
    return normalized_expiry > now


async def ensure_local_test_identity(
    *,
    db: LocalIdentityDatabase,
    manager: LocalIdentityManager,
    email: str,
    password: str,
    display_name: str,
) -> LocalTestIdentityResult:
    """Converge one synthetic identity through the public Identity SDK."""
    user = await db.get_user_by_email(email)
    created = user is None
    password_changed = False
    profile_changed = False

    if user is None:
        await manager.register(email, password, display_name)
        user = await db.get_user_by_email(email)
        if user is None:
            raise RuntimeError("Identity registration did not create the test account")
        password_changed = True
    elif user.status in {"disabled", "locked"}:
        raise ValueError(
            "The synthetic account is disabled or locked; use another test email "
            "instead of bypassing its security state"
        )
    else:
        if not await verify_password(password, user.password_hash):
            if not await manager.forgot_password(email):
                raise RuntimeError("Identity password-reset preparation failed")
            user = await db.get_user_by_email(email)
            if user is None or not _valid_token(
                user.password_reset_token,
                user.password_reset_token_exp,
            ):
                raise RuntimeError("Identity password-reset token is unavailable")
            reset_token = user.password_reset_token
            if reset_token is None:
                raise RuntimeError("Identity password-reset token is unavailable")
            if not await manager.reset_password(reset_token, password):
                raise RuntimeError("Identity password reset failed")
            password_changed = True

        if user.display_name != display_name:
            await manager.update_profile(user.id, display_name)
            profile_changed = True

    user = await db.get_user_by_email(email)
    if user is None:
        raise RuntimeError("The seeded Identity account is unavailable")
    if not user.email_verified:
        if user.status != "pending_verification":
            raise ValueError(
                "The synthetic account has an inconsistent verification state"
            )
        if not _valid_token(user.email_verify_token, user.email_verify_token_exp):
            if not await manager.resend_verification(email):
                raise RuntimeError("Identity verification preparation failed")
            user = await db.get_user_by_email(email)
        if user is None or not _valid_token(
            user.email_verify_token,
            user.email_verify_token_exp,
        ):
            raise RuntimeError("Identity verification token is unavailable")
        verification_token = user.email_verify_token
        if verification_token is None:
            raise RuntimeError("Identity verification token is unavailable")
        if not await manager.verify_email(verification_token):
            raise RuntimeError("Identity email verification failed")

    await db.reset_failed_login_attempts(user.id)
    final_user = await db.get_user_by_email(email)
    if (
        final_user is None
        or final_user.status != "active"
        or not final_user.email_verified
    ):
        raise RuntimeError("The seeded Identity account is not active and verified")
    return LocalTestIdentityResult(
        user_id=final_user.id,
        email=final_user.email,
        created=created,
        password_changed=password_changed,
        profile_changed=profile_changed,
        verified=final_user.email_verified,
    )


async def seed_local_test_identity(
    *,
    database_url: str,
    email: str,
    password: str,
    display_name: str,
    jwt_secret: str,
) -> LocalTestIdentityResult:
    """Open one bounded Identity SDK pool and seed a synthetic account."""
    url = make_url(database_url)
    pool = await create_pool(
        host=url.host or "127.0.0.1",
        port=url.port or 55432,
        database=url.database or "sanchezcloud",
        user=url.username or "",
        password=url.password or "",
        min_size=1,
        max_size=1,
    )
    try:
        db = AsyncpgUserDatabase(pool_factory=lambda: pool)
        manager = UserManager(
            db=db,
            email_sender=None,
            config=AuthConfig(client_id="scholens", jwt_secret=jwt_secret),
        )
        return await ensure_local_test_identity(
            db=db,
            manager=manager,
            email=email,
            password=password,
            display_name=display_name,
        )
    finally:
        await close_pool(pool)


__all__ = [
    "LocalTestIdentityResult",
    "ensure_local_test_identity",
    "seed_local_test_identity",
]
