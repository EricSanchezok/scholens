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


def test_sync_backend_resolves_each_users_key_and_pins_endpoint(monkeypatch):
    from app.llm import backend as module
    from app.database.models import ReasoningLevel

    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "shared-must-not-be-used")
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_BASE_URL", "https://untrusted.invalid")
    monkeypatch.setattr(user_credentials, "SessionLocal", MagicMock())
    monkeypatch.setattr(
        user_credentials,
        "require_deepseek_key",
        lambda db, *, user_id: f"user-{user_id}",
    )
    factory = MagicMock()
    monkeypatch.setattr(module.openai, "OpenAI", factory)
    backend = module.ProfiledChatBackend()
    factory.assert_not_called()
    with pytest.raises(AppError):
        backend._client(ReasoningLevel.STANDARD)
    for user_id in (7, 8, 7):
        with llm_usage_context(user_id=user_id, feature="title"):
            backend._client(ReasoningLevel.STANDARD)
    assert [c.kwargs["api_key"] for c in factory.call_args_list] == [
        "user-7",
        "user-8",
        "user-7",
    ]
    assert all(
        c.kwargs["base_url"] == "https://api.deepseek.com"
        for c in factory.call_args_list
    )


@pytest.mark.asyncio
async def test_title_sidecar_propagates_owner_context_to_thread(monkeypatch):
    from uuid import uuid4
    from app.bootstrap.adapters import conversation_chat
    from app.llm.token_credits import current_usage_context

    observed = []

    def generate(history):
        context = current_usage_context()
        observed.append((context.user_id, context.feature))
        return "A short title"

    monkeypatch.setattr(
        conversation_chat.initial_conversation_title_generator, "generate", generate
    )
    assert (
        await conversation_chat._generate_initial_title(
            user_id=17, user_query="Question", conversation_id=uuid4()
        )
        == "A short title"
    )
    assert observed == [(17, "conversation_title")]
    assert current_usage_context() is None


def test_new_catalog_includes_deepseek_but_legacy_response_keeps_original_enums():
    from app.modules.integrations.connections.application import (
        IntegrationConnectionResponse,
        IntegrationListResponse,
    )
    from app.transport.http.public_v1 import connections, integrations

    workflow = MagicMock()
    workflow.list.return_value = IntegrationListResponse(
        items=[
            IntegrationConnectionResponse(
                provider=IntegrationProvider.SCHOLIGHT,
                category="built_in",
                connection_method="built_in",
                managed=True,
                state="connected",
                enabled=True,
            ),
            IntegrationConnectionResponse(
                provider=IntegrationProvider.DEEPSEEK,
                category="ai",
                connection_method="credential",
                managed=False,
                state="disconnected",
                enabled=False,
            ),
        ]
    )
    actor = SimpleNamespace(id=7)
    assert len(connections.list_integrations(workflow=workflow, actor=actor).items) == 2
    legacy = integrations.list_integrations(workflow=workflow, actor=actor)
    assert [x.provider for x in legacy.items] == ["scholight"]
    assert integrations._integration_provider("mineru") == IntegrationProvider.MINERU
    with pytest.raises(AppError) as error:
        integrations._integration_provider("deepseek")
    assert error.value.code == "integration_not_supported"


@pytest.mark.parametrize(
    "provider,table",
    [
        (IntegrationProvider.DEEPSEEK, "model_connections"),
        (IntegrationProvider.MINERU, "integration_connections"),
    ],
)
def test_provider_reads_and_deletes_use_the_owning_credential_store(provider, table):
    from app.modules.integrations.connections.infrastructure.repository import (
        SqlAlchemyIntegrationGateway,
    )

    db = MagicMock()
    db.scalar.return_value = None
    gateway = SqlAlchemyIntegrationGateway(db)
    assert gateway.get_owned(user_id=7, provider=provider) is None
    statement = db.scalar.call_args.args[0]
    assert statement.get_final_froms()[0].name == table
    assert statement.compile().params == {"user_id_1": 7, "provider_1": provider.value}
    gateway.delete(user_id=7, provider=provider)
    statement = db.execute.call_args.args[0]
    assert statement.table.name == table
    assert statement.compile().params == {"user_id_1": 7, "provider_1": provider.value}
