"""Cloud-authenticated paper collection view preferences."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.papers.application.preferences import (
    PaperListPreferencesResponse,
    PaperListPreferencesUpdateRequest,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends


paper_list_preferences_router = APIRouter(tags=["papers"])


@paper_list_preferences_router.get(
    "/paper-list-preferences",
    response_model=PaperListPreferencesResponse,
)
def get_paper_list_preferences(
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> PaperListPreferencesResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_list_preferences.get(actor=actor)
    )


@paper_list_preferences_router.put(
    "/paper-list-preferences",
    response_model=PaperListPreferencesResponse,
)
def update_paper_list_preferences(
    request: PaperListPreferencesUpdateRequest,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> PaperListPreferencesResponse:
    return executor.command(
        lambda capabilities: capabilities.paper_list_preferences.update(
            actor=actor,
            operation=operation,
            request=request,
        )
    )
