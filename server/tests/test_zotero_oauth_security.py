from datetime import UTC, datetime, timedelta
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests
from pydantic import ValidationError

from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.bootstrap.workflows.zotero import ZoteroWorkflow
from app.modules.integrations.zotero.application.contracts import (
    ZoteroOAuthAuthorizationRequest,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    ZoteroConnectionRepository,
)
from app.modules.integrations.zotero.infrastructure.oauth import (
    ACCESS_TOKEN_URL,
    OAUTH_TIMEOUT,
    REQUEST_TOKEN_URL,
    ZoteroAuthClient,
    _close_oauth_response,
)
from app.shared.application import (
    OperationContextFactory,
    RequestReference,
    SignedCursorCodec,
)
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from sqlalchemy.orm import Session


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

    first = gateway.consume_oauth_callback(oauth_token="request-token")
    second = gateway.consume_oauth_callback(oauth_token="request-token")

    assert first is not None
    assert first.request_token.secret == "decrypted-secret"
    assert first.return_path == "/library"
    assert second is None
    repository.delete_pending.assert_called_once_with(pending=pending)


def test_oauth_workflow_commits_pending_consumption_before_provider_exchange() -> None:
    consume_session = MagicMock(spec=Session)
    sessions = [consume_session]
    zotero = MagicMock()
    zotero.consume_oauth_callback.return_value = None
    executor = SqlAlchemyApplicationExecutor(
        MagicMock(side_effect=sessions),
        lambda _session: SimpleNamespace(zotero=zotero),
    )
    operations = MagicMock()
    workflow = ZoteroWorkflow(
        executor=executor,
        operations=operations,
        operation_factory=OperationContextFactory(),
        cursors=SignedCursorCodec(
            "test-zotero-cursor-key",
            revision="zotero-test-v1",
            error_code="zotero_cursor_invalid",
        ),
    )

    result = workflow.callback(
        oauth_token="already-consumed",
        oauth_verifier="verifier",
        request=RequestReference(uuid4()),
    )

    assert result.state == "zotero_oauth_expired"
    consume_session.commit.assert_called_once_with()
    consume_session.rollback.assert_not_called()
    consume_session.close.assert_called_once_with()
    operations.exchange_access_token.assert_not_called()


def test_oauth_session_ignores_proxy_environment_and_closes_token_response() -> None:
    client = ZoteroAuthClient()
    client.client_key = "client-key"
    client.client_secret = "client-secret"
    client.redirect_uri = "https://app.example/callback"
    session = client._oauth_session()
    assert session.trust_env is False
    response = MagicMock(spec=requests.Response)
    response.content = b"oauth_token=request&oauth_token_secret=secret"

    assert _close_oauth_response(response) is response
    response.close.assert_called_once_with()


def test_oauth_token_exchanges_use_timeouts_and_redacted_errors(caplog) -> None:
    client = ZoteroAuthClient()
    client.client_key = "client-key"
    client.client_secret = "client-secret"
    client.redirect_uri = "https://app.example/callback"
    request_session = MagicMock()
    request_session.fetch_request_token.side_effect = RuntimeError(
        "request-token-secret"
    )
    access_session = MagicMock()
    access_session.fetch_access_token.return_value = {
        "userID": "42",
        "oauth_token_secret": "api-key",
    }

    with patch.object(
        client,
        "_oauth_session",
        side_effect=[request_session, access_session],
    ):
        with caplog.at_level(logging.ERROR):
            assert client.get_request_token() is None
        access = client.get_access_token("request", "secret", "verifier")

    assert "request-token-secret" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"
    request_session.fetch_request_token.assert_called_once_with(
        REQUEST_TOKEN_URL,
        timeout=OAUTH_TIMEOUT,
        allow_redirects=False,
        hooks={"response": _close_oauth_response},
    )
    request_session.close.assert_called_once_with()
    access_session.fetch_access_token.assert_called_once_with(
        ACCESS_TOKEN_URL,
        timeout=OAUTH_TIMEOUT,
        allow_redirects=False,
        hooks={"response": _close_oauth_response},
    )
    access_session.close.assert_called_once_with()
    assert access is not None
    assert access.zotero_user_id == "42"
