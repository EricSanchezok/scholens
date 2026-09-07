from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.llm.token_credits import llm_usage_context
from app.llm import user_credentials
from app.modules.integrations.connections.domain import IntegrationProvider
from app.modules.integrations.connections.infrastructure.deepseek import (
    require_deepseek_key,
)
from app.modules.integrations.connections.infrastructure.secrets import (
    AesGcmIntegrationCredentialCipher,
)
from app.shared.domain import AppError
from app.bootstrap.settings import AppSettings


def test_missing_and_disabled_connections_never_use_process_key(monkeypatch):
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "platform-must-not-be-used")
    db = MagicMock()
    for record in [None, SimpleNamespace(enabled=False)]:
        db.get.return_value = record
        with pytest.raises(AppError) as error:
            require_deepseek_key(db, user_id=7)
        assert error.value.code == "deepseek_credential_required"


def test_user_encryption_cannot_be_replayed_for_another_account():
    cipher = AesGcmIntegrationCredentialCipher(
        AppSettings().integration_credential_encryption_key
    )
    encrypted = cipher.encrypt(
        user_id=7, provider=IntegrationProvider.DEEPSEEK, plaintext="user-seven-secret"
    )
    db = MagicMock()
    db.get.return_value = SimpleNamespace(enabled=True, credential_ciphertext=encrypted)
    assert require_deepseek_key(db, user_id=7) == "user-seven-secret"
    with pytest.raises(AppError) as error:
        require_deepseek_key(db, user_id=8)
    assert error.value.code == "deepseek_credential_invalid"
    assert "user-seven-secret" not in str(error.value)


def test_model_key_requires_scoped_user_and_restores_nested_identity(monkeypatch):
    monkeypatch.setattr(user_credentials, "SessionLocal", MagicMock())
    monkeypatch.setattr(
        user_credentials, "require_deepseek_key", lambda db, *, user_id: str(user_id)
    )
    with pytest.raises(AppError):
        user_credentials.current_deepseek_key()
    with llm_usage_context(user_id=7, feature="chat"):
        assert user_credentials.current_deepseek_key() == "7"
        with llm_usage_context(user_id=8, feature="translation"):
            assert user_credentials.current_deepseek_key() == "8"
        assert user_credentials.current_deepseek_key() == "7"
    with pytest.raises(AppError):
        user_credentials.current_deepseek_key()


@pytest.mark.parametrize("feature", ["chat", "translation", "research"])
def test_model_features_fail_at_entry_when_key_is_missing(feature):
    from uuid import uuid4
    from app.bootstrap.adapters.conversation_chat_data import (
        SqlAlchemyConversationChatData,
    )
    from app.modules.translations.infrastructure.entitlements import (
        SqlTranslationEntitlements,
    )
    from app.modules.research.infrastructure.generation import SqlGenerationEntitlements

    db = MagicMock()
    db.get.return_value = None
    actor = SimpleNamespace(id=7)
    with pytest.raises(AppError) as error:
        if feature == "chat":
            SqlAlchemyConversationChatData(db).prepare(
                actor=actor, conversation_id=uuid4()
            )
        elif feature == "translation":
            SqlTranslationEntitlements(db).has_ai_connection(actor=actor)
        else:
            SqlGenerationEntitlements(db).require_ai_connection(actor=actor)
    assert error.value.code == "deepseek_credential_required"
    db.execute.assert_not_called()
