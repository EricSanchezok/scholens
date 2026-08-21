from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.modules.identity.application import (
    SharedAvatarNotFoundError,
    SharedAvatarUnavailableError,
)
from app.modules.identity.infrastructure.shared_avatars import (
    SanchezCloudSharedAvatarReader,
    SharedAvatarSettings,
)
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectPermissionSet,
)
from app.modules.research.application.contracts import AnnotationThreadListResponse
from app.shared.application import Actor, AvatarReference
from app.shared.domain import AppError, FailureKind
from app.transport.http.public_v1.avatar_presenters import (
    present_annotation_threads,
    present_project_collaborators,
)
from app.transport.http.public_v1.identity import get_my_avatar
from sanchezcloud_identity.exceptions import AvatarNotFoundError

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
AVATAR = AvatarReference(
    url="https://avatars.example/signed",
    version=UUID("11111111-1111-1111-1111-111111111111"),
    expires_at=NOW + timedelta(minutes=15),
)


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


class FakeAvatarReader:
    def __init__(self, avatars: dict[int, AvatarReference]) -> None:
        self.avatars = avatars
        self.requested: set[int] = set()

    async def get(self, user_id: int) -> AvatarReference:
        try:
            return self.avatars[user_id]
        except KeyError as exc:
            raise SharedAvatarNotFoundError from exc

    async def get_many(self, user_ids: set[int]) -> dict[int, AvatarReference]:
        self.requested = user_ids
        return {
            user_id: self.avatars[user_id]
            for user_id in user_ids
            if user_id in self.avatars
        }


def _actor() -> Actor:
    return Actor(
        id=42,
        email="reader@example.com",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


def test_shared_avatar_settings_are_optional_outside_production() -> None:
    settings = SharedAvatarSettings(_env_file=None)

    assert settings.configured is False
    assert settings.url_ttl_seconds == 900
    assert settings.max_concurrency == 8
    assert settings.cache_max_entries == 2048
    assert settings.cache_refresh_skew_seconds == 60
    assert settings.missing_cache_ttl_seconds == 60


@pytest.mark.asyncio
async def test_reader_fails_closed_when_unconfigured() -> None:
    reader = SanchezCloudSharedAvatarReader(None, max_concurrency=1)

    with pytest.raises(SharedAvatarUnavailableError):
        await reader.get(42)


@pytest.mark.asyncio
async def test_reader_maps_identity_avatar_and_missing_record() -> None:
    manager = MagicMock()
    manager.get = AsyncMock(
        side_effect=[
            SimpleNamespace(
                url=AVATAR.url,
                version=AVATAR.version,
                expires_at=AVATAR.expires_at,
            ),
            AvatarNotFoundError("missing"),
        ]
    )
    reader = SanchezCloudSharedAvatarReader(manager, max_concurrency=1)

    assert await reader.get(42) == AVATAR
    with pytest.raises(SharedAvatarNotFoundError):
        await reader.get(43)


@pytest.mark.asyncio
async def test_repeated_batches_reuse_positive_and_negative_cache_entries() -> None:
    async def load(user_id: int) -> SimpleNamespace:
        if user_id == 43:
            raise AvatarNotFoundError("missing")
        return SimpleNamespace(
            url=AVATAR.url,
            version=AVATAR.version,
            expires_at=AVATAR.expires_at,
        )

    manager = MagicMock()
    manager.get = AsyncMock(side_effect=load)
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=2,
        clock=MutableClock(),
    )

    first = await reader.get_many({42, 43})
    second = await reader.get_many({42, 43})

    assert first == second == {42: AVATAR}
    assert manager.get.await_count == 2


@pytest.mark.asyncio
async def test_positive_cache_refreshes_before_signed_url_expiry() -> None:
    clock = MutableClock()
    refreshed = AVATAR.model_copy(
        update={
            "url": "https://avatars.example/refreshed",
            "expires_at": NOW + timedelta(minutes=20),
        }
    )
    manager = MagicMock()
    manager.get = AsyncMock(
        side_effect=[
            SimpleNamespace(**AVATAR.model_dump()),
            SimpleNamespace(**refreshed.model_dump()),
        ]
    )
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=1,
        cache_refresh_skew_seconds=60,
        clock=clock,
    )

    assert await reader.get(42) == AVATAR
    clock.advance(minutes=13)
    assert await reader.get(42) == AVATAR
    clock.advance(minutes=1, seconds=1)
    assert await reader.get(42) == refreshed
    assert manager.get.await_count == 2


@pytest.mark.asyncio
async def test_negative_cache_expires_after_short_ttl() -> None:
    clock = MutableClock()
    manager = MagicMock()
    manager.get = AsyncMock(
        side_effect=[
            AvatarNotFoundError("missing"),
            SimpleNamespace(**AVATAR.model_dump()),
        ]
    )
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=1,
        missing_cache_ttl_seconds=30,
        clock=clock,
    )

    with pytest.raises(SharedAvatarNotFoundError):
        await reader.get(42)
    with pytest.raises(SharedAvatarNotFoundError):
        await reader.get(42)
    assert manager.get.await_count == 1

    clock.advance(seconds=31)
    assert await reader.get(42) == AVATAR
    assert manager.get.await_count == 2


@pytest.mark.asyncio
async def test_cache_evicts_least_recently_used_entries_at_its_bound() -> None:
    async def load(user_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            url=f"https://avatars.example/{user_id}",
            version=AVATAR.version,
            expires_at=AVATAR.expires_at,
        )

    manager = MagicMock()
    manager.get = AsyncMock(side_effect=load)
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=1,
        cache_max_entries=1,
        clock=MutableClock(),
    )

    await reader.get(42)
    await reader.get(43)
    await reader.get(42)

    assert manager.get.await_count == 3


@pytest.mark.asyncio
async def test_concurrent_reads_for_one_user_share_one_upstream_call() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def load(_user_id: int) -> SimpleNamespace:
        started.set()
        await release.wait()
        return SimpleNamespace(**AVATAR.model_dump())

    manager = MagicMock()
    manager.get = AsyncMock(side_effect=load)
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=4,
        clock=MutableClock(),
    )

    reads = [asyncio.create_task(reader.get(42)) for _ in range(8)]
    await started.wait()
    await asyncio.sleep(0)
    assert manager.get.await_count == 1
    release.set()

    assert await asyncio.gather(*reads) == [AVATAR] * 8
    assert manager.get.await_count == 1


@pytest.mark.asyncio
async def test_upstream_failures_are_not_cached() -> None:
    manager = MagicMock()
    manager.get = AsyncMock(
        side_effect=[
            RuntimeError("temporary"),
            SimpleNamespace(**AVATAR.model_dump()),
        ]
    )
    reader = SanchezCloudSharedAvatarReader(
        manager,
        max_concurrency=1,
        clock=MutableClock(),
    )

    with pytest.raises(SharedAvatarUnavailableError):
        await reader.get(42)
    assert await reader.get(42) == AVATAR
    assert manager.get.await_count == 2


@pytest.mark.asyncio
async def test_current_avatar_endpoint_maps_success_and_absence() -> None:
    response = await get_my_avatar(_actor(), FakeAvatarReader({42: AVATAR}))

    assert response.url == AVATAR.url
    assert response.expires_at == AVATAR.expires_at

    with pytest.raises(AppError) as exc_info:
        await get_my_avatar(_actor(), FakeAvatarReader({}))
    assert exc_info.value.kind is FailureKind.NOT_FOUND
    assert exc_info.value.code == "shared_avatar_not_found"

    unavailable = MagicMock()
    unavailable.get = AsyncMock(side_effect=SharedAvatarUnavailableError)
    with pytest.raises(AppError) as unavailable_info:
        await get_my_avatar(_actor(), unavailable)
    assert unavailable_info.value.kind is FailureKind.UNAVAILABLE
    assert unavailable_info.value.retryable is True


@pytest.mark.asyncio
async def test_project_presenter_deduplicates_visible_users_and_keeps_fallbacks() -> (
    None
):
    response = ProjectCollaboratorListResponse(
        items=[
            ProjectCollaboratorResponse(
                user_id=42,
                display_name="Reader",
                email="reader@example.com",
                is_owner=True,
                permissions=ProjectPermissionSet(
                    edit_project=True,
                    manage_papers=True,
                    manage_collaborators=True,
                ),
                joined_at=NOW,
            ),
            ProjectCollaboratorResponse(
                user_id=43,
                display_name="No Avatar",
                email="fallback@example.com",
                is_owner=False,
                permissions=ProjectPermissionSet(),
                joined_at=NOW,
            ),
        ]
    )
    reader = FakeAvatarReader({42: AVATAR})

    presented = await present_project_collaborators(response, reader)

    assert reader.requested == {42, 43}
    assert presented.items[0].avatar is not None
    assert presented.items[0].avatar.url == AVATAR.url
    assert presented.items[1].avatar is None


@pytest.mark.asyncio
async def test_annotation_presenter_enriches_thread_and_comment_creators() -> None:
    response = AnnotationThreadListResponse.model_validate(
        {
            "items": [
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "audience": {"kind": "personal"},
                    "target_document_id": "33333333-3333-3333-3333-333333333333",
                    "created_by": {"id": 42, "display_name": "Reader"},
                    "created_at": NOW,
                    "quote_text": "Quoted text",
                    "position": None,
                    "color": "yellow",
                    "role": "user",
                    "mode": "discussion",
                    "comment_count": 1,
                    "last_activity_at": NOW,
                    "status": "open",
                    "resolved_by": None,
                    "resolved_at": None,
                    "capabilities": {
                        "reply": True,
                        "recolor": True,
                        "resolve": True,
                        "reopen": False,
                        "delete": True,
                    },
                    "comments": [
                        {
                            "id": "44444444-4444-4444-4444-444444444444",
                            "thread_id": "22222222-2222-2222-2222-222222222222",
                            "content": "Comment",
                            "role": "user",
                            "created_by": {"id": 42, "display_name": "Reader"},
                            "created_at": NOW,
                            "updated_at": NOW,
                            "can_edit": True,
                            "can_delete": True,
                        }
                    ],
                }
            ]
        }
    )
    reader = FakeAvatarReader({42: AVATAR})

    presented = await present_annotation_threads(response, reader)

    assert reader.requested == {42}
    assert presented.items[0].created_by.avatar is not None
    assert presented.items[0].comments[0].created_by.avatar is not None
