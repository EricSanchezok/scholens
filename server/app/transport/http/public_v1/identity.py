from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.container import (
    build_identity_session_bootstrap,
    build_shared_avatar_reader,
)
from app.bootstrap.execution import (
    get_application_executor,
    get_operation_context_factory,
)
from app.modules.identity.application import (
    AuthBootstrapResponse,
    BootstrapIdentitySession,
    SharedAvatarNotFoundError,
    SharedAvatarReader,
    SharedAvatarUnavailableError,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    AvatarReference,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationInitiator,
    OperationContextFactory,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind
from app.transport.http.observability import (
    attach_operation_context,
    ensure_request_id,
)
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Request, Response, status

router = APIRouter()


@router.post("/auth/bootstrap", response_model=AuthBootstrapResponse)
async def bootstrap_session(
    request: Request,
    response: Response,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    session_bootstrap: BootstrapIdentitySession = Depends(
        build_identity_session_bootstrap
    ),
) -> AuthBootstrapResponse:
    cookie = session_bootstrap.cookie
    refresh_token = request.cookies.get(cookie.name)
    if not refresh_token:
        raise AppError(
            code="auth_session_missing",
            message="The session is unavailable",
            kind=FailureKind.UNAUTHENTICATED,
        )
    operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(
            request=RequestReference(request_id=ensure_request_id(request))
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    session = await session_bootstrap.execute(
        refresh_token,
        resolve_actor=lambda user_id: executor.command(
            lambda capabilities: capabilities.identity.resolve_session_actor(
                user_id,
                operation=operation,
            )
        ),
        user_agent=request.headers.get("user-agent"),
    )
    request.state.authenticated = True
    attach_operation_context(request, operation, actor_id=str(session.actor.id))
    response.set_cookie(
        key=cookie.name,
        value=session.refresh_token,
        max_age=cookie.max_age_seconds,
        secure=cookie.secure,
        httponly=True,
        samesite=cookie.samesite,
        path=cookie.path,
    )
    return AuthBootstrapResponse(access_token=session.access_token, actor=session.actor)


@router.get("/me", response_model=Actor)
async def get_me(
    actor: Actor = Depends(get_required_user),
) -> Actor:
    return actor


@router.get(
    "/me/avatar",
    response_model=AvatarReference,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "The user has no shared avatar."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "The shared avatar service is unavailable."
        },
    },
)
async def get_my_avatar(
    actor: Actor = Depends(get_required_user),
    avatar_reader: SharedAvatarReader = Depends(build_shared_avatar_reader),
) -> AvatarReference:
    try:
        avatar = await avatar_reader.get(actor.id)
    except SharedAvatarNotFoundError as exc:
        raise AppError(
            code="shared_avatar_not_found",
            message="Shared avatar not found",
            kind=FailureKind.NOT_FOUND,
        ) from exc
    except SharedAvatarUnavailableError as exc:
        raise AppError(
            code="shared_avatar_unavailable",
            message="Shared avatar service unavailable",
            kind=FailureKind.UNAVAILABLE,
        ) from exc
    return avatar
