from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.modules.integrations.zotero.application.contracts import (
    ZoteroOAuthAuthorizationRequest,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    ZoteroConnectionRepository,
)


@pytest.mark.parametrize(
    "return_path",
    ["https://evil.example/callback", "//evil.example/callback", "library", "/x#y"],
)
def test_oauth_return_path_rejects_external_and_ambiguous_urls(
    return_path: str,
) -> None:
    with pytest.raises(ValidationError):
        ZoteroOAuthAuthorizationRequest(return_path=return_path, intent="import")


def test_pending_oauth_secret_is_encrypted_with_a_short_ttl() -> None:
    db = MagicMock()
    cipher = MagicMock()
    cipher.encrypt.return_value = "encrypted-secret"
    with patch(
        "app.modules.integrations.zotero.infrastructure.connection_repository.SqlAlchemyIntegrationGateway"
    ):
        repository = ZoteroConnectionRepository(db, cipher=cipher)

    before = datetime.now(UTC)
    pending = repository.create_pending(
        user_id=7,
        oauth_token="request-token",
        oauth_token_secret="plain-secret",
        return_path="/library?tab=papers",
        intent="import",
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )

    assert pending.oauth_token_secret_ciphertext == "encrypted-secret"
    assert "plain-secret" not in repr(pending)
    assert before + timedelta(minutes=14) < pending.expires_at
    assert pending.expires_at <= before + timedelta(minutes=16)
    cipher.encrypt.assert_called_once()


def test_oauth_callback_is_consumed_once() -> None:
    repository = MagicMock()
    pending = SimpleNamespace(
        user_id=7,
        oauth_token="request-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        return_path="/library",
        intent="import",
    )
    repository.get_pending_by_token.side_effect = [pending, None]
    repository.pending_secret.return_value = "decrypted-secret"
    gateway = DefaultZoteroGateway(MagicMock(), connections=repository)

    first = gateway.oauth_callback(oauth_token="request-token")
    second = gateway.oauth_callback(oauth_token="request-token")

    assert first is not None
    assert first.request_token.secret == "decrypted-secret"
    assert first.return_path == "/library"
    assert second is None
    repository.delete_pending.assert_called_once_with(pending=pending)
