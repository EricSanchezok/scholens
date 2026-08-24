from __future__ import annotations

import base64

import pytest
from app.shared.application import SignedCursorCodec
from app.shared.domain import AppError

_URLSAFE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _codec() -> SignedCursorCodec:
    return SignedCursorCodec(
        "test-cursor-secret",
        revision="test:v1",
        error_code="test_cursor_invalid",
    )


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_signed_cursor_round_trips_canonical_unpadded_urlsafe_base64() -> None:
    codec = _codec()

    offset_cursor = codec.encode(fingerprint="actor=1", offset=42)
    keyset_cursor = codec.encode_keyset(
        fingerprint="actor=1&filter=active",
        values=("2026-08-24T10:00:00Z", "item-id"),
    )

    assert "=" not in offset_cursor
    assert "=" not in keyset_cursor
    assert codec.decode(cursor=offset_cursor, fingerprint="actor=1") == 42
    assert codec.decode_keyset(
        cursor=keyset_cursor,
        fingerprint="actor=1&filter=active",
        arity=2,
    ) == ("2026-08-24T10:00:00Z", "item-id")


@pytest.mark.parametrize("suffix", ["=", "\n", "+"])
def test_signed_cursor_rejects_noncanonical_base64_characters(suffix: str) -> None:
    codec = _codec()
    cursor = codec.encode(fingerprint="actor=1", offset=42)

    with pytest.raises(AppError) as exc_info:
        codec.decode(cursor=f"{cursor}{suffix}", fingerprint="actor=1")

    assert exc_info.value.code == "test_cursor_invalid"


def test_signed_cursor_rejects_an_unbounded_encoded_value() -> None:
    with pytest.raises(AppError) as exc_info:
        _codec().decode(cursor="a" * 4097, fingerprint="actor=1")

    assert exc_info.value.code == "test_cursor_invalid"


def test_signed_cursor_rejects_a_padding_bit_alias() -> None:
    codec = _codec()
    alias: str | None = None
    canonical: str | None = None
    for offset in range(100):
        candidate_cursor = codec.encode(fingerprint="actor=1", offset=offset)
        decoded = _decode_base64(candidate_cursor)
        for character in _URLSAFE_ALPHABET:
            candidate_alias = f"{candidate_cursor[:-1]}{character}"
            if (
                candidate_alias != candidate_cursor
                and _decode_base64(candidate_alias) == decoded
            ):
                canonical = candidate_cursor
                alias = candidate_alias
                break
        if alias is not None:
            break

    assert canonical is not None
    assert alias is not None
    with pytest.raises(AppError) as exc_info:
        codec.decode(cursor=alias, fingerprint="actor=1")

    assert exc_info.value.code == "test_cursor_invalid"
