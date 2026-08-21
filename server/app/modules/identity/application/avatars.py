"""Read-only shared-avatar contracts exposed to Scholens transports."""

from __future__ import annotations

from typing import Protocol

from app.shared.application import AvatarReference


class SharedAvatarNotFoundError(Exception):
    """Raised when an identity has no shared avatar."""


class SharedAvatarUnavailableError(Exception):
    """Raised when the configured shared-avatar service cannot answer."""


class SharedAvatarReader(Protocol):
    """Read avatars without exposing identity persistence to product code."""

    async def get(self, user_id: int) -> AvatarReference: ...

    async def get_many(self, user_ids: set[int]) -> dict[int, AvatarReference]: ...


__all__ = [
    "SharedAvatarNotFoundError",
    "SharedAvatarReader",
    "SharedAvatarUnavailableError",
]
