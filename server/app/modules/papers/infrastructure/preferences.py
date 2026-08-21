"""SQLAlchemy storage for account paper-list preferences."""

from __future__ import annotations

from app.modules.papers.application.preferences import (
    PaperListColumn,
    PaperListPreferencesRecord,
)
from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, Boolean, ForeignKey, func
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
        model = self._db.execute(
            insert(PaperListPreference)
            .values(
                user_id=user_id,
                visible_columns=values,
                preview_open=preferences.preview_open,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "visible_columns": values,
                    "preview_open": preferences.preview_open,
                    "updated_at": func.now(),
                },
            )
            .returning(PaperListPreference)
        ).scalar_one()
        return _record(model)


def _record(model: PaperListPreference) -> PaperListPreferencesRecord:
    return PaperListPreferencesRecord(
        visible_columns=tuple(
            PaperListColumn(value) for value in model.visible_columns
        ),
        preview_open=model.preview_open,
    )
