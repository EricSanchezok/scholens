from app.bootstrap.workflows.billing import BillingUsageWorkflow, BillingWorkflow
from app.modules.billing.application.contracts import (
    SubscriptionResponse,
    UsagePeriod,
    CapacityResponse,
)
from app.shared.application import Actor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from app.transport.http.public_v1.billing.dependencies import (
    get_billing_usage_workflow,
    get_billing_workflow,
)
from app.transport.http.public_v1.billing.legacy_usage import UsageResponse
from fastapi import APIRouter, Depends

subscription_status_router = APIRouter()
usage_router = APIRouter()


@subscription_status_router.get("/subscription", response_model=SubscriptionResponse)
def get_user_subscription(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> SubscriptionResponse:
    return workflow.get_subscription(
        actor=current_user,
        operation=operation,
    )


@usage_router.get("/usage", response_model=UsageResponse, deprecated=True)
def get_user_usage(
    period: UsagePeriod = UsagePeriod.CURRENT_WEEK,
    workflow: BillingUsageWorkflow = Depends(get_billing_usage_workflow),
    current_user: Actor = Depends(get_required_user),
) -> UsageResponse:
    return UsageResponse.from_capacity(workflow.get_usage(current_user, period), period)


@usage_router.get("/capacity", response_model=CapacityResponse)
def get_user_capacity(
    workflow: BillingUsageWorkflow = Depends(get_billing_usage_workflow),
    current_user: Actor = Depends(get_required_user),
) -> CapacityResponse:
    return workflow.get_usage(current_user, UsagePeriod.CURRENT_WEEK)
