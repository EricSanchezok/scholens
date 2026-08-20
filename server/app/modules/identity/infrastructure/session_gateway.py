"""sanchezcloud-identity adapter for browser-session bootstrap."""

from sanchezcloud_identity.exceptions import AuthError, DBError
from sanchezcloud_identity.jwt import decode_refresh_token

from app.modules.identity.application.sessions import RotatedBrowserSession
from app.modules.identity.infrastructure import sanchezcloud_identity as runtime
from app.shared.domain import AppError, FailureKind


def _session_expired() -> AppError:
    return AppError(
        code="auth_session_expired",
        message="The session is unavailable",
        kind=FailureKind.UNAUTHENTICATED,
    )


class SanchezcloudIdentitySessionGateway:
    def refresh_subject(self, refresh_token: str) -> int:
        try:
            payload = decode_refresh_token(refresh_token, config=runtime.auth_config)
            return int(str(payload["sub"]))
        except (AuthError, KeyError, TypeError, ValueError) as exc:
            raise _session_expired() from exc

    async def rotate(
        self,
        refresh_token: str,
        *,
        user_agent: str | None,
    ) -> RotatedBrowserSession:
        try:
            (
                access_token,
                rotated_refresh_token,
            ) = await runtime.auth_manager.refresh_token(
                refresh_token,
                user_agent=user_agent,
            )
        except DBError as exc:
            raise AppError(
                code="auth_service_unavailable",
                message="Authentication is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        except AuthError as exc:
            raise _session_expired() from exc
        return RotatedBrowserSession(
            access_token=access_token,
            refresh_token=rotated_refresh_token,
        )
