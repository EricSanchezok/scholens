"""HTTP dependencies for active usage and dormant payment workflows."""

from typing import cast

from app.bootstrap.workflows.billing import BillingUsageWorkflow, BillingWorkflow
from fastapi import Request


def get_billing_workflow(request: Request) -> BillingWorkflow:
    return cast(BillingWorkflow, request.app.state.billing_workflow)


def get_billing_usage_workflow(request: Request) -> BillingUsageWorkflow:
    return cast(BillingUsageWorkflow, request.app.state.billing_usage_workflow)


__all__ = ["get_billing_usage_workflow", "get_billing_workflow"]
