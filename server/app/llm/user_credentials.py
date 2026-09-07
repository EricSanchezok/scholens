"""Model credentials scoped to the authenticated workload context."""

from app.database.database import SessionLocal
from app.llm.token_credits import current_usage_context
from app.modules.integrations.connections.infrastructure.deepseek import (
    require_deepseek_key,
)
from app.shared.domain import AppError, FailureKind


def current_deepseek_key() -> str:
    context = current_usage_context()
    if context is None:
        raise AppError(
            code="deepseek_credential_required",
            message="A user-owned DeepSeek connection is required",
            kind=FailureKind.CONFLICT,
        )
    with SessionLocal() as db:
        return require_deepseek_key(db, user_id=context.user_id)
