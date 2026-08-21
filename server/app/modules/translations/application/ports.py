"""Replaceable ports and immutable facts for translation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID

from app.modules.translations.application.contracts import FullTranslationDisplay
from app.shared.application import Actor


@dataclass(frozen=True, slots=True)
class TranslationPreferencesRecord:
    source_language: str
    target_language: str
    custom_instructions: str | None
    auto_translate_selection: bool
    full_translation_display: FullTranslationDisplay
    translate_references: bool
    show_translation_marker: bool


class TranslationPreferencesGateway(Protocol):
    def get(self, *, user_id: int) -> TranslationPreferencesRecord | None: ...

    def upsert(
        self,
        *,
        user_id: int,
        preferences: TranslationPreferencesRecord,
    ) -> TranslationPreferencesRecord: ...


class TranslationEntitlements(Protocol):
    def has_token_credits(self, *, actor: Actor) -> bool: ...


@dataclass(frozen=True, slots=True)
class PreparedTranslation:
    document_id: UUID
    paper_title: str | None
    source_text: str
    source_language: str
    target_language: str
    custom_instructions: str | None
    context_kind: str = "selection"
    block_id: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationStreamSpec:
    paper_title: str | None
    source_text: str
    source_language: str
    target_language: str
    custom_instructions: str | None
    context_kind: str = "selection"


class TranslationStreamProvider(Protocol):
    def prompt_revision(self) -> str: ...

    def model_revision(self) -> str: ...

    def stream(self, spec: TranslationStreamSpec) -> AsyncIterator[str]: ...


class TranslationStreamFailureKind(str, Enum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    USAGE_SETTLEMENT_FAILED = "usage_settlement_failed"
    INTERRUPTED = "interrupted"


class TranslationStreamFailure(RuntimeError):
    def __init__(self, kind: TranslationStreamFailureKind) -> None:
        self.kind = kind
        super().__init__(kind.value)


@dataclass(frozen=True, slots=True)
class TranslationResultValue:
    translated_text: str
    target_language: str


class TranslationResultStore(Protocol):
    async def get(self, key: str) -> TranslationResultValue | None: ...

    async def set(
        self,
        *,
        identity: TranslationResultIdentity,
        value: TranslationResultValue,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class TranslationResultIdentity:
    key: str
    context_kind: str
    document_id: UUID
    block_id: str | None
    target_language: str
    source_hash: str
    instructions_hash: str
    prompt_revision: str
    profile_revision: str


class TranslationSingleFlight(Protocol):
    async def acquire(self, key: str) -> str | None: ...

    async def release(self, key: str, lease_token: str) -> None: ...


@dataclass(frozen=True, slots=True)
class TranslationCapacityLease:
    key: str
    member: str


class TranslationCapacity(Protocol):
    async def enforce_rate(
        self,
        *,
        user_id: int,
        client_ip: str,
    ) -> None: ...

    async def acquire(
        self,
        *,
        user_id: int,
        operation_id: UUID,
    ) -> TranslationCapacityLease: ...

    async def release(self, lease: TranslationCapacityLease) -> None: ...


@dataclass(frozen=True, slots=True)
class TranslationStreamEvent:
    event: str
    data: dict[str, object]
