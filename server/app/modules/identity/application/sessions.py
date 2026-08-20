"""Browser-session bootstrap independent of the shared identity adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.shared.application import Actor


@dataclass(frozen=True, slots=True)
class RefreshCookieSettings:
    name: str
    max_age_seconds: int
    secure: bool
    samesite: Literal["lax", "strict", "none"]
    path: str


@dataclass(frozen=True, slots=True)
class RotatedBrowserSession:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class BootstrappedIdentitySession:
    access_token: str
    actor: Actor
    refresh_token: str


class IdentitySessionGateway(Protocol):
    def refresh_subject(self, refresh_token: str) -> int: ...

    async def rotate(
        self,
        refresh_token: str,
        *,
        user_agent: str | None,
    ) -> RotatedBrowserSession: ...


class BootstrapIdentitySession:
    """Resolve product access before committing refresh-token rotation."""

    def __init__(
        self,
        gateway: IdentitySessionGateway,
        *,
        cookie: RefreshCookieSettings,
    ) -> None:
        self._gateway = gateway
        self.cookie = cookie

    async def execute(
        self,
        refresh_token: str,
        *,
        resolve_actor: Callable[[int], Actor],
        user_agent: str | None,
    ) -> BootstrappedIdentitySession:
        user_id = self._gateway.refresh_subject(refresh_token)
        actor = resolve_actor(user_id)
        rotated = await self._gateway.rotate(
            refresh_token,
            user_agent=user_agent,
        )
        return BootstrappedIdentitySession(
            access_token=rotated.access_token,
            actor=actor,
            refresh_token=rotated.refresh_token,
        )
