from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.container import build_identity_session_bootstrap
from app.bootstrap.execution import (
    get_application_executor,
    get_operation_context_factory,
)
from app.modules.identity.application import (
    AuthBootstrapResponse,
    BootstrapIdentitySession,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
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
from fastapi import APIRouter, Depends, Request, Response

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
