"""Resolve the acting user's DeepSeek connection, never process credentials."""

from __future__ import annotations

from app.bootstrap.settings import AppSettings
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure.models import (
    ModelConnection,
)
from app.modules.integrations.connections.infrastructure.secrets import (
    AesGcmIntegrationCredentialCipher,
)
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


def require_deepseek_key(db: Session, *, user_id: int) -> str:
    record = db.get(ModelConnection, (user_id, IntegrationProvider.DEEPSEEK.value))
    if record is None or not record.enabled:
        raise AppError(
            code="deepseek_credential_required",
            message="Connect your DeepSeek API key in Settings to use AI",
            kind=FailureKind.CONFLICT,
            details={"required_integration": "deepseek"},
        )
    try:
        return AesGcmIntegrationCredentialCipher(
            AppSettings().integration_credential_encryption_key
        ).decrypt(
            user_id=user_id,
            provider=IntegrationProvider.DEEPSEEK,
            ciphertext=record.credential_ciphertext,
        )
    except ValueError:
        raise AppError(
            code="deepseek_credential_invalid",
            message="Replace your DeepSeek API key in Settings",
            kind=FailureKind.UNPROCESSABLE,
            details={"required_integration": "deepseek"},
        ) from None
