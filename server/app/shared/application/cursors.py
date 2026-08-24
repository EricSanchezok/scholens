"""Signed opaque cursors shared by replaceable paginated capabilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from typing import NoReturn, cast

from app.shared.domain import AppError, FailureKind

_UNPADDED_URLSAFE_BASE64 = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_CURSOR_CHARACTERS = 4096


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant {value}")


class SignedCursorCodec:
    def __init__(
        self,
        secret: str,
        *,
        revision: str,
        error_code: str,
        error_kind: FailureKind = FailureKind.CONFLICT,
    ) -> None:
        self._secret = secret.encode()
        self._revision = revision
        self._error_code = error_code
        self._error_kind = error_kind

    def encode(self, *, fingerprint: str, offset: int) -> str:
        return self._encode(
            fingerprint=fingerprint,
            position={"offset": offset},
        )

    def encode_keyset(
        self,
        *,
        fingerprint: str,
        values: tuple[str, ...],
    ) -> str:
        """Sign a transport-opaque keyset position."""

        return self._encode(
            fingerprint=fingerprint,
            position={"keyset": list(values)},
        )

    def _encode(
        self,
        *,
        fingerprint: str,
        position: dict[str, object],
    ) -> str:
        payload = json.dumps(
            {
                "revision": self._revision,
                "request_hash": hashlib.sha256(fingerprint.encode()).hexdigest(),
                **position,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def decode(self, *, cursor: str, fingerprint: str) -> int:
        data = self._decode(cursor=cursor, fingerprint=fingerprint)
        offset = data.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            self._raise_invalid()
        return offset

    def decode_keyset(
        self,
        *,
        cursor: str,
        fingerprint: str,
        arity: int,
    ) -> tuple[str, ...]:
        """Verify and return a keyset position with a fixed shape."""

        data = self._decode(cursor=cursor, fingerprint=fingerprint)
        values = data.get("keyset")
        if (
            not isinstance(values, list)
            or len(values) != arity
            or any(not isinstance(value, str) for value in values)
        ):
            self._raise_invalid()
        return tuple(cast(list[str], values))

    def _decode(self, *, cursor: str, fingerprint: str) -> dict[str, object]:
        data: dict[str, object] = {}
        try:
            cursor_is_canonical = (
                len(cursor) <= _MAX_CURSOR_CHARACTERS
                and _UNPADDED_URLSAFE_BASE64.fullmatch(cursor) is not None
            )
            if not cursor_is_canonical:
                raise ValueError("cursor is not canonical URL-safe base64")
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
            canonical = base64.urlsafe_b64encode(decoded).decode().rstrip("=")
            if not hmac.compare_digest(cursor, canonical):
                raise ValueError("cursor has a non-canonical base64 encoding")
            if len(decoded) <= hashlib.sha256().digest_size:
                raise ValueError("cursor payload is missing")
            payload, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("cursor signature is invalid")
            decoded_data: object = json.loads(
                payload,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(decoded_data, dict):
                raise ValueError("cursor payload must be an object")
            data = cast(dict[str, object], decoded_data)
            valid = (
                data["revision"] == self._revision
                and data["request_hash"]
                == hashlib.sha256(fingerprint.encode()).hexdigest()
            )
        except (binascii.Error, KeyError, TypeError, ValueError):
            valid = False
            data = {}
        if not valid:
            self._raise_invalid()
        return data

    def _raise_invalid(self) -> NoReturn:
        raise AppError(
            code=self._error_code,
            message="The cursor is invalid or expired",
            kind=self._error_kind,
        )
