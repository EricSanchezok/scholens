"""Zotero version-checkpoint and entitlement behavior."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.modules.integrations.zotero.application.zotero import ZoteroAutoImportCursor
from app.modules.integrations.zotero.application.contracts import (
    ZoteroSyncPreferencesRequest,
)
from app.shared.application import Actor
from app.shared.domain import AppError


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _connection(*, auto_import_enabled: bool = False):
    return SimpleNamespace(
        configuration={
            "auto_import_enabled": auto_import_enabled,
            "auto_import_library_version": 100 if auto_import_enabled else None,
        },
        created_at=None,
        credential_revision=uuid4(),
        last_error_code=None,
    )


def test_enabling_auto_import_records_current_library_version() -> None:
    connection = _connection()
    connections = MagicMock()
    connections.get_by_user_id.return_value = connection
    connections.credential_revision_is_current.side_effect = (
        lambda *, revision, **_kwargs: revision == connection.credential_revision
    )
    connections.credentials.return_value = (
        "42",
        "secret",
        connection.credential_revision,
    )
    connections.update_configuration.side_effect = lambda **kwargs: setattr(
        connection, "configuration", kwargs["configuration"]
    )
    gateway = DefaultZoteroGateway(MagicMock(), connections=connections)

    with (
        patch(
            "app.bootstrap.adapters.zotero_gateway.can_user_auto_sync_zotero",
            return_value=True,
        ),
        patch(
            "app.bootstrap.adapters.zotero_gateway.zotero_import_repository.get_max_last_synced_at",
            return_value=None,
        ),
    ):
        status = gateway.set_sync_preferences(
            actor=_actor(),
            request=ZoteroSyncPreferencesRequest(auto_import_enabled=True),
            library_version=321,
        )

    configuration = connections.update_configuration.call_args.kwargs["configuration"]
    assert configuration["auto_import_enabled"] is True
    assert configuration["auto_import_library_version"] == 321
    assert status.auto_import_state == "active"


def test_basic_cannot_enable_auto_import() -> None:
    connection = _connection()
    connections = MagicMock()
    connections.get_by_user_id.return_value = connection
    gateway = DefaultZoteroGateway(MagicMock(), connections=connections)

    with patch(
        "app.bootstrap.adapters.zotero_gateway.can_user_auto_sync_zotero",
        return_value=False,
    ):
        with pytest.raises(AppError) as raised:
            gateway.set_sync_preferences(
                actor=_actor(),
                request=ZoteroSyncPreferencesRequest(auto_import_enabled=True),
                library_version=321,
            )

    assert raised.value.code == "zotero_auto_import_requires_researcher"
    connections.update_configuration.assert_not_called()


def test_checkpoint_advances_only_for_matching_credential_revision() -> None:
    connection = _connection(auto_import_enabled=True)
    connections = MagicMock()
    connections.get_by_user_id.return_value = connection
    connections.credential_revision_is_current.side_effect = (
        lambda *, revision, **_kwargs: revision == connection.credential_revision
    )
    gateway = DefaultZoteroGateway(MagicMock(), connections=connections)

    assert not gateway.advance_sync_checkpoint(
        user_id=7,
        credential_revision=uuid4(),
        library_version=500,
        auto_import_cursor=ZoteroAutoImportCursor(library_version=500),
    )
    connections.update_configuration.assert_not_called()

    assert gateway.advance_sync_checkpoint(
        user_id=7,
        credential_revision=connection.credential_revision,
        library_version=500,
        auto_import_cursor=ZoteroAutoImportCursor(
            library_version=500,
            start=50,
        ),
    )
    configuration = connections.update_configuration.call_args.kwargs["configuration"]
    assert configuration["last_sync_library_version"] == 500
    assert configuration["auto_import_library_version"] == 500
    assert configuration["auto_import_start"] == 50
    assert "last_sync_at" in configuration
    connections.credential_revision_is_current.assert_called_with(
        user_id=7,
        revision=connection.credential_revision,
        lock=True,
    )
