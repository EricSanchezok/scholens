"""Pure normalization and request-fingerprint rules for paper translation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from uuid import UUID

DEFAULT_TARGET_LANGUAGE = "zh-CN"
DEFAULT_SOURCE_LANGUAGE = "auto"
MAX_LANGUAGE_TAG_CHARS = 35
MAX_CUSTOM_INSTRUCTIONS_CHARS = 2_000
MAX_SOURCE_TEXT_CHARS = 5_000
MAX_REFLOW_BLOCK_CHARS = 25_000
MAX_TRANSLATED_TEXT_CHARS = 80_000

_LANGUAGE_TAG = re.compile(
    r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$",
)
_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")


def normalize_language_tag(value: str) -> str:
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > MAX_LANGUAGE_TAG_CHARS
        or _LANGUAGE_TAG.fullmatch(candidate) is None
    ):
        raise ValueError("invalid_language_tag")
    parts = candidate.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def normalize_source_language(value: str) -> str:
    candidate = value.strip()
    return (
        DEFAULT_SOURCE_LANGUAGE
        if candidate.casefold() == DEFAULT_SOURCE_LANGUAGE
        else normalize_language_tag(candidate)
    )


def resolve_target_language(*, stored_language: str | None) -> str:
    for candidate in (stored_language, DEFAULT_TARGET_LANGUAGE):
        if candidate is None:
            continue
        try:
            return normalize_language_tag(candidate)
        except ValueError:
            continue
    return DEFAULT_TARGET_LANGUAGE


def normalize_custom_instructions(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    if len(normalized) > MAX_CUSTOM_INSTRUCTIONS_CHARS:
        raise ValueError("custom_instructions_too_long")
    return normalized


def normalize_source_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("source_text_empty")

    paragraphs: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(normalized):
        lines = [
            _HORIZONTAL_WHITESPACE.sub(" ", line).strip()
            for line in paragraph.split("\n")
        ]
        lines = [line for line in lines if line]
        if not lines:
            continue
        joined = lines[0]
        for line in lines[1:]:
            joined += line if joined.endswith("-") else f" {line}"
        paragraphs.append(joined)
    result = "\n\n".join(paragraphs)
    if not result:
        raise ValueError("source_text_empty")
    if len(result) > MAX_SOURCE_TEXT_CHARS:
        raise ValueError("source_text_too_long")
    return result


def normalize_reflow_source(value: str) -> str:
    """Normalize a persisted reflow block without damaging Markdown structure."""

    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("source_text_empty")
    if len(normalized) > MAX_REFLOW_BLOCK_CHARS:
        raise ValueError("source_text_too_long")
    return normalized


def validate_translated_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > MAX_TRANSLATED_TEXT_CHARS:
        raise ValueError("translated_text_invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class TranslationFingerprint:
    schema_revision: str
    prompt_revision: str
    model_revision: str
    context_kind: str
    block_id: str | None
    document_id: UUID
    paper_title_hash: str
    source_text: str
    source_language: str
    target_language: str
    custom_instructions_hash: str


def translation_identity_key(identity: TranslationFingerprint) -> str:
    payload = json.dumps(
        asdict(identity),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def translation_source_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def translation_instructions_hash(value: str | None) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


def translation_paper_title_hash(value: str | None) -> str:
    normalized = unicodedata.normalize("NFC", value or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()
