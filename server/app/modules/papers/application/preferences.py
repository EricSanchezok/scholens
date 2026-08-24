"""Account-scoped preferences for dense paper collection views."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PaperListColumn(StrEnum):
    READING_TIME = "reading_time"
    STATUS = "status"
    TAGS = "tags"
    AUTHORS = "authors"
    PUBLICATION = "publication"
    LAST_OPENED = "last_opened"
    ADDED_AT = "added_at"
    DOI = "doi"


class PaperListSizedColumn(StrEnum):
    PAPER = "paper"
    READING_TIME = "reading_time"
    STATUS = "status"
    TAGS = "tags"
    AUTHORS = "authors"
    PUBLICATION = "publication"
    LAST_OPENED = "last_opened"
    ADDED_AT = "added_at"
    DOI = "doi"


DEFAULT_PAPER_LIST_COLUMNS = (
    PaperListColumn.READING_TIME,
    PaperListColumn.STATUS,
    PaperListColumn.TAGS,
    PaperListColumn.AUTHORS,
    PaperListColumn.PUBLICATION,
    PaperListColumn.LAST_OPENED,
)

DEFAULT_PAPER_LIST_COLUMN_WIDTHS = {
    PaperListSizedColumn.PAPER: 360,
    PaperListSizedColumn.READING_TIME: 112,
    PaperListSizedColumn.STATUS: 96,
    PaperListSizedColumn.TAGS: 160,
    PaperListSizedColumn.AUTHORS: 176,
    PaperListSizedColumn.PUBLICATION: 144,
    PaperListSizedColumn.LAST_OPENED: 120,
    PaperListSizedColumn.ADDED_AT: 120,
    PaperListSizedColumn.DOI: 160,
}
PAPER_LIST_COLUMN_WIDTH_LIMITS = {
    PaperListSizedColumn.PAPER: (160, 1600),
    PaperListSizedColumn.READING_TIME: (96, 240),
    PaperListSizedColumn.STATUS: (88, 960),
    PaperListSizedColumn.TAGS: (128, 400),
    PaperListSizedColumn.AUTHORS: (144, 520),
    PaperListSizedColumn.PUBLICATION: (128, 400),
    PaperListSizedColumn.LAST_OPENED: (112, 280),
    PaperListSizedColumn.ADDED_AT: (112, 280),
    PaperListSizedColumn.DOI: (144, 480),
}
DEFAULT_PAPER_LIST_PREVIEW_WIDTH = 512
MIN_PAPER_LIST_PREVIEW_WIDTH = 400
MAX_PAPER_LIST_PREVIEW_WIDTH = 720


class PaperListColumnWidth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: PaperListSizedColumn
    width: int

    @model_validator(mode="after")
    def validate_column_width(self) -> PaperListColumnWidth:
        minimum, maximum = PAPER_LIST_COLUMN_WIDTH_LIMITS[self.column]
        if not minimum <= self.width <= maximum:
            raise ValueError(
                f"{self.column.value} width must be between {minimum} and {maximum}"
            )
        return self


class PaperListPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_columns: list[PaperListColumn]
    preview_open: bool
    column_widths: list[PaperListColumnWidth] | None = None
    preview_width: int | None = Field(
        default=None,
        ge=MIN_PAPER_LIST_PREVIEW_WIDTH,
        le=MAX_PAPER_LIST_PREVIEW_WIDTH,
    )

    @field_validator("visible_columns")
    @classmethod
    def reject_duplicates(cls, value: list[PaperListColumn]) -> list[PaperListColumn]:
        if len(value) != len(set(value)):
            raise ValueError("visible_columns must contain unique values")
        return value

    @field_validator("column_widths")
    @classmethod
    def reject_duplicate_widths(
        cls, value: list[PaperListColumnWidth] | None
    ) -> list[PaperListColumnWidth] | None:
        if value is not None and len(value) != len({item.column for item in value}):
            raise ValueError("column_widths must contain unique columns")
        return value


class PaperListPreferencesResponse(BaseModel):
    visible_columns: list[PaperListColumn]
    preview_open: bool
    column_widths: list[PaperListColumnWidth]
    preview_width: int


@dataclass(frozen=True, slots=True)
class PaperListPreferencesRecord:
    visible_columns: tuple[PaperListColumn, ...]
    preview_open: bool
    column_widths: tuple[PaperListColumnWidth, ...]
    preview_width: int


class PaperListPreferencesGateway(Protocol):
    def get(self, *, user_id: int) -> PaperListPreferencesRecord | None: ...

    def upsert(
        self,
        *,
        user_id: int,
        preferences: PaperListPreferencesRecord,
    ) -> PaperListPreferencesRecord: ...


PAPER_LIST_PREFERENCES_UPDATED = OperationAction("paper_list_preferences.updated")


class PaperListPreferences:
    def __init__(
        self,
        *,
        gateway: PaperListPreferencesGateway,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def get(self, *, actor: Actor) -> PaperListPreferencesResponse:
        return self._response(self._gateway.get(user_id=actor.id))

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: PaperListPreferencesUpdateRequest,
    ) -> PaperListPreferencesResponse:
        current = self._gateway.get(user_id=actor.id)
        widths = {
            item.column: item.width
            for item in (
                current.column_widths
                if current is not None
                else _default_column_widths()
            )
        }
        if request.column_widths is not None:
            widths.update({item.column: item.width for item in request.column_widths})
        record = self._gateway.upsert(
            user_id=actor.id,
            preferences=PaperListPreferencesRecord(
                visible_columns=tuple(request.visible_columns),
                preview_open=request.preview_open,
                column_widths=tuple(
                    PaperListColumnWidth(column=column, width=widths[column])
                    for column in PaperListSizedColumn
                ),
                preview_width=(
                    request.preview_width
                    if request.preview_width is not None
                    else current.preview_width
                    if current is not None
                    else DEFAULT_PAPER_LIST_PREVIEW_WIDTH
                ),
            ),
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=PAPER_LIST_PREFERENCES_UPDATED,
            resources=(ResourceRef("paper_list_preferences", str(actor.id)),),
        )
        return self._response(record)

    @staticmethod
    def _response(
        record: PaperListPreferencesRecord | None,
    ) -> PaperListPreferencesResponse:
        return PaperListPreferencesResponse(
            visible_columns=list(
                record.visible_columns
                if record is not None
                else DEFAULT_PAPER_LIST_COLUMNS
            ),
            preview_open=record.preview_open if record is not None else True,
            column_widths=list(
                record.column_widths if record is not None else _default_column_widths()
            ),
            preview_width=(
                record.preview_width
                if record is not None
                else DEFAULT_PAPER_LIST_PREVIEW_WIDTH
            ),
        )


def _default_column_widths() -> tuple[PaperListColumnWidth, ...]:
    return tuple(
        PaperListColumnWidth(
            column=column,
            width=DEFAULT_PAPER_LIST_COLUMN_WIDTHS[column],
        )
        for column in PaperListSizedColumn
    )
