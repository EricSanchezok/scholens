"""Account-scoped preferences for dense paper collection views."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext
from pydantic import BaseModel, ConfigDict, field_validator


class PaperListColumn(StrEnum):
    STATUS = "status"
    TAGS = "tags"
    AUTHORS = "authors"
    PUBLICATION = "publication"
    LAST_OPENED = "last_opened"
    ADDED_AT = "added_at"
    DOI = "doi"


DEFAULT_PAPER_LIST_COLUMNS = (
    PaperListColumn.STATUS,
    PaperListColumn.TAGS,
    PaperListColumn.AUTHORS,
    PaperListColumn.PUBLICATION,
    PaperListColumn.LAST_OPENED,
)


class PaperListPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_columns: list[PaperListColumn]
    preview_open: bool

    @field_validator("visible_columns")
    @classmethod
    def reject_duplicates(cls, value: list[PaperListColumn]) -> list[PaperListColumn]:
        if len(value) != len(set(value)):
            raise ValueError("visible_columns must contain unique values")
        return value


class PaperListPreferencesResponse(BaseModel):
    visible_columns: list[PaperListColumn]
    preview_open: bool


@dataclass(frozen=True, slots=True)
class PaperListPreferencesRecord:
    visible_columns: tuple[PaperListColumn, ...]
    preview_open: bool


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
        record = self._gateway.upsert(
            user_id=actor.id,
            preferences=PaperListPreferencesRecord(
                visible_columns=tuple(request.visible_columns),
                preview_open=request.preview_open,
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
        )
