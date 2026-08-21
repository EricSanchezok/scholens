from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner
from sanchezcloud_identity.models.user import UserRecord

from app.cli import cli
from app.operator_cli import local_test_account
from app.operator_cli.local_test_account import ensure_local_test_identity


class FakeIdentityDatabase:
    def __init__(self, user: UserRecord | None = None) -> None:
        self.user = user
        self.failed_attempt_resets: list[int] = []

    async def get_user_by_email(self, _email: str) -> UserRecord | None:
        return self.user.model_copy(deep=True) if self.user is not None else None

    async def reset_failed_login_attempts(self, user_id: int) -> None:
        self.failed_attempt_resets.append(user_id)


class FakeIdentityManager:
    def __init__(self, db: FakeIdentityDatabase) -> None:
        self.db = db
        self.password_reset_requests = 0
        self.password_resets = 0
        self.profile_updates = 0
        self.verification_resends = 0

    async def register(
        self,
        email: str,
        _password: str,
        display_name: str | None = None,
    ) -> None:
        self.db.user = UserRecord(
            id=7,
            email=email,
            password_hash="fixture-hash",
            display_name=display_name,
            status="pending_verification",
            email_verified=False,
            email_verify_token="verify-token",
            email_verify_token_exp=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def resend_verification(self, _email: str) -> bool:
        self.verification_resends += 1
        assert self.db.user is not None
        self.db.user.email_verify_token = "replacement-verify-token"
        self.db.user.email_verify_token_exp = datetime.now(UTC) + timedelta(minutes=5)
        return True

    async def verify_email(self, token: str) -> bool:
        assert self.db.user is not None
        if token != self.db.user.email_verify_token:
            return False
        self.db.user.email_verified = True
        self.db.user.status = "active"
        self.db.user.email_verify_token = None
        self.db.user.email_verify_token_exp = None
        return True

    async def forgot_password(self, _email: str) -> bool:
        self.password_reset_requests += 1
        assert self.db.user is not None
        self.db.user.password_reset_token = "reset-token"
        self.db.user.password_reset_token_exp = datetime.now(UTC) + timedelta(minutes=5)
        return True

    async def reset_password(self, token: str, _new_password: str) -> bool:
        assert self.db.user is not None
        if token != self.db.user.password_reset_token:
            return False
        self.password_resets += 1
        self.db.user.password_hash = "updated-hash"
        self.db.user.password_reset_token = None
        self.db.user.password_reset_token_exp = None
        return True

    async def update_profile(self, user_id: int, display_name: str | None) -> object:
        assert self.db.user is not None and self.db.user.id == user_id
        self.profile_updates += 1
        self.db.user.display_name = display_name
        return object()


@pytest.mark.asyncio
async def test_seed_creates_and_verifies_a_new_synthetic_identity() -> None:
    db = FakeIdentityDatabase()
    manager = FakeIdentityManager(db)

    result = await ensure_local_test_identity(
        db=db,
        manager=manager,
        email="developer@example.com",
        password="local-password!",
        display_name="Local Developer",
    )

    assert result.created is True
    assert result.changed is True
    assert result.password_changed is True
    assert result.verified is True
    assert db.user is not None
    assert db.user.status == "active"
    assert db.failed_attempt_resets == [7]


@pytest.mark.asyncio
async def test_seed_is_unchanged_when_existing_identity_already_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeIdentityDatabase(
        UserRecord(
            id=9,
            email="developer@example.com",
            password_hash="matching-hash",
            display_name="Local Developer",
            status="active",
            email_verified=True,
        )
    )
    manager = FakeIdentityManager(db)

    async def password_matches(_password: str, _password_hash: str) -> bool:
        return True

    monkeypatch.setattr(local_test_account, "verify_password", password_matches)

    result = await ensure_local_test_identity(
        db=db,
        manager=manager,
        email="developer@example.com",
        password="local-password!",
        display_name="Local Developer",
    )

    assert result.changed is False
    assert manager.password_reset_requests == 0
    assert manager.password_resets == 0
    assert manager.profile_updates == 0


@pytest.mark.asyncio
async def test_seed_repairs_password_and_display_name_through_identity_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeIdentityDatabase(
        UserRecord(
            id=11,
            email="developer@example.com",
            password_hash="old-hash",
            display_name="Old name",
            status="active",
            email_verified=True,
        )
    )
    manager = FakeIdentityManager(db)

    async def password_differs(_password: str, _password_hash: str) -> bool:
        return False

    monkeypatch.setattr(local_test_account, "verify_password", password_differs)

    result = await ensure_local_test_identity(
        db=db,
        manager=manager,
        email="developer@example.com",
        password="replacement-password!",
        display_name="Local Developer",
    )

    assert result.password_changed is True
    assert result.profile_changed is True
    assert manager.password_reset_requests == 1
    assert manager.password_resets == 1
    assert manager.profile_updates == 1


@pytest.mark.asyncio
async def test_seed_refuses_to_bypass_locked_identity_state() -> None:
    db = FakeIdentityDatabase(
        UserRecord(
            id=13,
            email="developer@example.com",
            password_hash="hash",
            status="locked",
            email_verified=True,
        )
    )

    with pytest.raises(ValueError, match="disabled or locked"):
        await ensure_local_test_identity(
            db=db,
            manager=FakeIdentityManager(db),
            email="developer@example.com",
            password="local-password!",
            display_name="Local Developer",
        )


@pytest.mark.parametrize(
    ("environment", "database_url", "email", "message"),
    [
        (
            "production",
            "postgresql://scholens_app:secret@127.0.0.1:55432/sanchezcloud",
            "developer@example.com",
            "only in development",
        ),
        (
            "development",
            "postgresql://scholens_app:secret@database.example/sanchezcloud",
            "developer@example.com",
            "127.0.0.1:55432",
        ),
        (
            "development",
            "postgresql://scholens_app:secret@127.0.0.1:55432/sanchezcloud",
            "person@gmail.com",
            "reserved synthetic domain",
        ),
    ],
)
def test_cli_rejects_unsafe_test_account_targets(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    database_url: str,
    email: str,
    message: str,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("AUTH_DATABASE_URL", database_url)

    result = CliRunner().invoke(
        cli,
        [
            "dev",
            "seed-test-account",
            "--email",
            email,
            "--password",
            "local-password!",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert message in result.output
    assert "local-password!" not in result.output
