"""Persistent, source-text-free translation result cache."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from app.modules.translations.application import (
    TranslationResultIdentity,
    TranslationResultValue,
)
from app.modules.translations.infrastructure.models import TranslationResult
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


class SqlTranslationResultStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> TranslationResultValue | None:
        return await asyncio.to_thread(self._get, key)

    async def set(
        self,
        *,
        identity: TranslationResultIdentity,
        value: TranslationResultValue,
    ) -> None:
        await asyncio.to_thread(self._set, identity, value)

    def _get(self, key: str) -> TranslationResultValue | None:
        with self._session_factory() as db:
            result = db.scalar(
                select(TranslationResult).where(TranslationResult.identity_key == key)
            )
            if result is None:
                return None
            return TranslationResultValue(
                translated_text=result.translated_text,
                target_language=result.target_language,
            )

    def _set(
        self,
        identity: TranslationResultIdentity,
        value: TranslationResultValue,
    ) -> None:
        with self._session_factory() as db:
            with db.begin():
                db.execute(
                    insert(TranslationResult)
                    .values(
                        id=uuid.uuid4(),
                        identity_key=identity.key,
                        context_kind=identity.context_kind,
                        document_id=identity.document_id,
                        block_id=identity.block_id,
                        target_language=identity.target_language,
                        source_hash=identity.source_hash,
                        instructions_hash=identity.instructions_hash,
                        prompt_revision=identity.prompt_revision,
                        profile_revision=identity.profile_revision,
                        translated_text=value.translated_text,
                    )
                    .on_conflict_do_nothing(index_elements=["identity_key"])
                )
