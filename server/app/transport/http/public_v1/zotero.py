"""HTTP adapters for the Zotero integration."""

from uuid import UUID, uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor, get_zotero_workflow
from app.bootstrap.settings import AppSettings
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroCollectionPage,
    ZoteroConnectionStatus,
    ZoteroImportRequest,
    ZoteroLibraryPage,
    ZoteroOAuthAuthorizationRequest,
    ZoteroOperation,
    ZoteroSyncPreferencesRequest,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    RequestReference,
)
from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse

zotero_router = APIRouter()
zotero_oauth_router = APIRouter()


@zotero_oauth_router.post(
    "/authorizations",
    response_model=ZoteroConnectResponse,
    status_code=status.HTTP_201_CREATED,
)
def zotero_connect(
    request: ZoteroOAuthAuthorizationRequest,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> ZoteroConnectResponse:
    return workflow.connect(actor=current_user, operation=operation, request=request)


@zotero_oauth_router.get(
    "/callback",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
def zotero_callback(
    request: Request,
    oauth_token: str = Query(...),
    oauth_verifier: str = Query(...),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> RedirectResponse:
    settings: AppSettings = request.app.state.settings
    result = workflow.callback(
        oauth_token=oauth_token,
        oauth_verifier=oauth_verifier,
        request=RequestReference(uuid4()),
    )
    parsed = urlsplit(result.return_path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"zotero": result.state, "zotero_intent": result.intent})
    return_path = urlunsplit(("", "", parsed.path, urlencode(query), ""))
    return RedirectResponse(
        url=f"{settings.client_domain.rstrip('/')}{return_path}",
        status_code=status.HTTP_302_FOUND,
    )


@zotero_router.get("/status", response_model=ZoteroConnectionStatus)
def zotero_status(
    current_user: Actor = Depends(get_required_user),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> ZoteroConnectionStatus:
    return workflow.status(actor=current_user)


@zotero_router.put(
    "/sync-preferences",
    response_model=ZoteroConnectionStatus,
)
def zotero_sync_preferences(
    request: ZoteroSyncPreferencesRequest,
    current_user: Actor = Depends(get_required_user),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> ZoteroConnectionStatus:
    return workflow.set_sync_preferences(actor=current_user, request=request)


@zotero_router.delete(
    "/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
def zotero_disconnect(
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.zotero.disconnect(
            actor=current_user,
            operation=operation,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@zotero_router.get("/collections", response_model=ZoteroCollectionPage)
def zotero_collections(
    cursor: str | None = Query(default=None, max_length=2_048),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: Actor = Depends(get_required_user),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> ZoteroCollectionPage:
    return workflow.collections(actor=current_user, cursor=cursor, limit=limit)


@zotero_router.get("/library-items", response_model=ZoteroLibraryPage)
def zotero_library(
    cursor: str | None = Query(default=None, max_length=2_048),
    query: str | None = Query(default=None, max_length=240),
    collection_key: str | None = Query(default=None, max_length=64),
    item_type: str | None = Query(
        default=None, pattern="^(journalArticle|conferencePaper|preprint)$"
    ),
    sort: str = Query(
        default="modified_desc",
        pattern="^(modified_desc|added_desc|published_desc|title_asc|creator_asc)$",
    ),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: Actor = Depends(get_required_user),
    workflow: ZoteroWorkflow = Depends(get_zotero_workflow),
) -> ZoteroLibraryPage:
    return workflow.library(
        actor=current_user,
        cursor=cursor,
        query=query,
        collection_key=collection_key,
        item_type=item_type,
        sort=sort,
        limit=limit,
    )


@zotero_router.post(
    "/imports",
    response_model=ZoteroOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
async def zotero_import(
    request: ZoteroImportRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=128
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroOperation:
    return executor.command(
        lambda capabilities: capabilities.zotero.enqueue_import(
            actor=current_user,
            operation=operation,
            request=request,
            idempotency_key=idempotency_key,
        )
    )


@zotero_router.get("/imports/{operation_id}", response_model=ZoteroOperation)
def zotero_import_operation(
    operation_id: UUID,
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroOperation:
    return executor.query(
        lambda capabilities: capabilities.zotero.operation(
            actor=current_user,
            operation_id=operation_id,
            kind="import",
        )
    )


@zotero_router.delete("/imports/{operation_id}", response_model=ZoteroOperation)
def zotero_cancel_import(
    operation_id: UUID,
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroOperation:
    return executor.command(
        lambda capabilities: capabilities.zotero.cancel_operation(
            actor=current_user,
            operation_id=operation_id,
            kind="import",
        )
    )


@zotero_router.post(
    "/sync-runs",
    response_model=ZoteroOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
def zotero_sync(
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=128
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroOperation:
    return executor.command(
        lambda capabilities: capabilities.zotero.enqueue_sync(
            actor=current_user,
            operation=operation,
            idempotency_key=idempotency_key,
        )
    )


@zotero_router.get("/sync-runs/{operation_id}", response_model=ZoteroOperation)
def zotero_sync_operation(
    operation_id: UUID,
    current_user: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ZoteroOperation:
    return executor.query(
        lambda capabilities: capabilities.zotero.operation(
            actor=current_user,
            operation_id=operation_id,
            kind="sync",
        )
    )
