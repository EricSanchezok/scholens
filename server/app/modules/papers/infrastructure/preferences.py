"""SQLAlchemy storage for account paper-list preferences."""

from __future__ import annotations

from app.modules.papers.application.preferences import (
    DEFAULT_PAPER_LIST_COLUMN_WIDTHS,
    PaperListColumn,
    PaperListColumnWidth,
    PaperListPreferencesRecord,
    PaperListSizedColumn,
)
from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column


class PaperListPreference(Base):
    __tablename__ = "paper_list_preferences"
    __table_args__ = ({"schema": "scholens"},)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    visible_columns: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
    )
    preview_open: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    column_widths: Mapped[dict[str, int]] = mapped_column(
        JSONB,
        nullable=False,
    )
    preview_width: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=512,
        server_default="512",
    )


class SqlAlchemyPaperListPreferences:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, *, user_id: int) -> PaperListPreferencesRecord | None:
        model = self._db.get(PaperListPreference, user_id)
        return _record(model) if model is not None else None

    def upsert(
        self,
        *,
        user_id: int,
        preferences: PaperListPreferencesRecord,
    ) -> PaperListPreferencesRecord:
        values = [column.value for column in preferences.visible_columns]
        column_widths = {
            item.column.value: item.width for item in preferences.column_widths
        }
        model = self._db.execute(
            insert(PaperListPreference)
            .values(
                user_id=user_id,
                visible_columns=values,
                preview_open=preferences.preview_open,
                column_widths=column_widths,
                preview_width=preferences.preview_width,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "visible_columns": values,
                    "preview_open": preferences.preview_open,
                    "column_widths": column_widths,
                    "preview_width": preferences.preview_width,
                    "updated_at": func.now(),
                },
            )
            .returning(PaperListPreference)
        ).scalar_one()
        return _record(model)


def _record(model: PaperListPreference) -> PaperListPreferencesRecord:
    stored_widths = {
        PaperListSizedColumn(column): width
        for column, width in model.column_widths.items()
    }
    reading_time_is_legacy_missing = (
        PaperListSizedColumn.READING_TIME not in stored_widths
    )
    visible_columns = [PaperListColumn(value) for value in model.visible_columns]
    if (
        reading_time_is_legacy_missing
        and PaperListColumn.READING_TIME not in visible_columns
    ):
        # Compatibility owner: Papers preferences. Remove after every retained
        # preference row has been rewritten or backfilled with a reading-time
        # width; until then, old accounts receive the new default-visible column.
        visible_columns.insert(0, PaperListColumn.READING_TIME)
    return PaperListPreferencesRecord(
        visible_columns=tuple(visible_columns),
        preview_open=model.preview_open,
        column_widths=tuple(
            PaperListColumnWidth(
                column=column,
                width=stored_widths.get(
                    column,
                    DEFAULT_PAPER_LIST_COLUMN_WIDTHS[column],
                ),
            )
            for column in PaperListSizedColumn
        ),
        preview_width=model.preview_width,
    )
