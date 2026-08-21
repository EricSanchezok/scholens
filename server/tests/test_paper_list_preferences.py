from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.papers.application.preferences import (
    DEFAULT_PAPER_LIST_COLUMNS,
    PaperListColumn,
    PaperListPreferences,
    PaperListPreferencesRecord,
    PaperListPreferencesUpdateRequest,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)


def _actor(user_id: int) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(request_id=uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


class _Gateway:
    def __init__(self) -> None:
        self.records: dict[int, PaperListPreferencesRecord] = {}

    def get(self, *, user_id: int) -> PaperListPreferencesRecord | None:
        return self.records.get(user_id)

    def upsert(
        self,
        *,
        user_id: int,
        preferences: PaperListPreferencesRecord,
    ) -> PaperListPreferencesRecord:
        self.records[user_id] = preferences
        return preferences


class _Journal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> object:
        self.entries.append(kwargs)
        return object()


def _preferences(gateway: _Gateway, journal: _Journal) -> PaperListPreferences:
    return PaperListPreferences(
        gateway=gateway,
        journal=cast(Any, journal),
    )


def test_paper_list_preferences_default_and_ordered_update() -> None:
    gateway = _Gateway()
    journal = _Journal()
    preferences = _preferences(gateway, journal)

    defaults = preferences.get(actor=_actor(7))
    assert defaults.visible_columns == list(DEFAULT_PAPER_LIST_COLUMNS)
    assert defaults.preview_open is True

    updated = preferences.update(
        actor=_actor(7),
        operation=_operation(),
        request=PaperListPreferencesUpdateRequest(
            visible_columns=[
                PaperListColumn.DOI,
                PaperListColumn.STATUS,
                PaperListColumn.AUTHORS,
            ],
            preview_open=False,
        ),
    )
    assert updated.visible_columns == [
        PaperListColumn.DOI,
        PaperListColumn.STATUS,
        PaperListColumn.AUTHORS,
    ]
    assert updated.preview_open is False
    assert len(journal.entries) == 1


def test_paper_list_preferences_are_isolated_and_read_across_sessions() -> None:
    gateway = _Gateway()
    first_session = _preferences(gateway, _Journal())
    second_session = _preferences(gateway, _Journal())

    first_session.update(
        actor=_actor(7),
        operation=_operation(),
        request=PaperListPreferencesUpdateRequest(
            visible_columns=[PaperListColumn.TAGS],
            preview_open=False,
        ),
    )

    assert second_session.get(actor=_actor(7)).visible_columns == [PaperListColumn.TAGS]
    assert second_session.get(actor=_actor(7)).preview_open is False
    assert second_session.get(actor=_actor(8)).visible_columns == list(
        DEFAULT_PAPER_LIST_COLUMNS
    )
    assert second_session.get(actor=_actor(8)).preview_open is True


@pytest.mark.parametrize(
    "visible_columns",
    [
        ["status", "status"],
        ["unsupported"],
    ],
)
def test_paper_list_preferences_reject_invalid_columns(
    visible_columns: list[str],
) -> None:
    with pytest.raises(ValidationError):
        PaperListPreferencesUpdateRequest.model_validate(
            {
                "visible_columns": visible_columns,
                "preview_open": True,
            }
        )
