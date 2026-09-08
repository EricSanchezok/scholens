"""Translation adapter over the shared Token Credits policy."""

from __future__ import annotations

from app.modules.integrations.connections.infrastructure.deepseek import (
    require_deepseek_key,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlTranslationEntitlements:
    def __init__(self, db: Session) -> None:
        self._db = db

    def has_ai_connection(self, *, actor: Actor) -> bool:
        require_deepseek_key(self._db, user_id=actor.id)
        return True
