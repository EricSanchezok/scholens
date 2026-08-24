from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.papers.application.preferences import (
    DEFAULT_PAPER_LIST_COLUMN_WIDTHS,
    DEFAULT_PAPER_LIST_COLUMNS,
    DEFAULT_PAPER_LIST_PREVIEW_WIDTH,
    PaperListColumn,
    PaperListSizedColumn,
    PaperListPreferences,
    PaperListPreferencesRecord,
    PaperListPreferencesUpdateRequest,
)
from app.modules.papers.infrastructure.preferences import (
    PaperListPreference,
    _record,
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
    assert defaults.visible_columns[0] == PaperListColumn.READING_TIME
    assert defaults.preview_open is True
    assert {item.column: item.width for item in defaults.column_widths} == (
        DEFAULT_PAPER_LIST_COLUMN_WIDTHS
    )
    assert defaults.preview_width == DEFAULT_PAPER_LIST_PREVIEW_WIDTH

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
    assert {item.column: item.width for item in updated.column_widths} == (
        DEFAULT_PAPER_LIST_COLUMN_WIDTHS
    )
    assert updated.preview_width == DEFAULT_PAPER_LIST_PREVIEW_WIDTH
    assert len(journal.entries) == 1


def test_legacy_preferences_gain_the_default_reading_time_column() -> None:
    record = _record(
        PaperListPreference(
            user_id=7,
            visible_columns=["status", "authors"],
            preview_open=True,
            column_widths={"paper": 420, "status": 112, "authors": 208},
            preview_width=512,
        )
    )

    assert record.visible_columns == (
        PaperListColumn.READING_TIME,
        PaperListColumn.STATUS,
        PaperListColumn.AUTHORS,
    )
    widths = {item.column: item.width for item in record.column_widths}
    assert widths[PaperListSizedColumn.PAPER] == 420
    assert (
        widths[PaperListSizedColumn.READING_TIME]
        == DEFAULT_PAPER_LIST_COLUMN_WIDTHS[PaperListSizedColumn.READING_TIME]
    )


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


def test_paper_list_preferences_merge_partial_layout_sizes() -> None:
    gateway = _Gateway()
    first_session = _preferences(gateway, _Journal())
    second_session = _preferences(gateway, _Journal())

    first_session.update(
        actor=_actor(7),
        operation=_operation(),
        request=PaperListPreferencesUpdateRequest.model_validate(
            {
                "visible_columns": ["status", "authors"],
                "preview_open": True,
                "column_widths": [
                    {"column": "authors", "width": 304},
                    {"column": "paper", "width": 520},
                ],
                "preview_width": 640,
            }
        ),
    )
    updated = second_session.update(
        actor=_actor(7),
        operation=_operation(),
        request=PaperListPreferencesUpdateRequest.model_validate(
            {
                "visible_columns": ["status"],
                "preview_open": False,
                "column_widths": [{"column": "status", "width": 144}],
            }
        ),
    )

    widths = {item.column: item.width for item in updated.column_widths}
    assert widths[PaperListSizedColumn.PAPER] == 520
    assert widths[PaperListSizedColumn.STATUS] == 144
    assert widths[PaperListSizedColumn.AUTHORS] == 304
    assert (
        widths[PaperListSizedColumn.TAGS]
        == DEFAULT_PAPER_LIST_COLUMN_WIDTHS[PaperListSizedColumn.TAGS]
    )
    assert updated.preview_width == 640


@pytest.mark.parametrize(
    ("column", "width"),
    [("paper", 160), ("paper", 1600), ("status", 88), ("status", 960)],
)
def test_paper_list_preferences_accept_expanded_width_boundaries(
    column: str, width: int
) -> None:
    request = PaperListPreferencesUpdateRequest.model_validate(
        {
            "visible_columns": ["status"],
            "preview_open": True,
            "column_widths": [{"column": column, "width": width}],
        }
    )

    assert request.column_widths is not None
    assert request.column_widths[0].width == width


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


@pytest.mark.parametrize(
    "column_widths,preview_width",
    [
        (
            [
                {"column": "paper", "width": 360},
                {"column": "paper", "width": 420},
            ],
            512,
        ),
        ([{"column": "paper", "width": 159}], 512),
        ([{"column": "paper", "width": 1601}], 512),
        ([{"column": "status", "width": 40}], 512),
        ([], 900),
    ],
)
def test_paper_list_preferences_reject_invalid_layout_sizes(
    column_widths: list[dict[str, object]],
    preview_width: int,
) -> None:
    with pytest.raises(ValidationError):
        PaperListPreferencesUpdateRequest.model_validate(
            {
                "visible_columns": ["status"],
                "preview_open": True,
                "column_widths": column_widths,
                "preview_width": preview_width,
            }
        )
