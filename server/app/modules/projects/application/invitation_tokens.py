"""Opaque, revisioned Project invitation bearer tokens."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DecodedProjectInvitationToken:
    invitation_id: UUID
    revision: int


class ProjectInvitationTokenCodec:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError(
                "PROJECT_INVITATION_TOKEN_SECRET must contain at least 32 UTF-8 bytes"
            )
        self._secret = secret.encode("utf-8")

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        if ProjectInvitationTokenCodec._encode(decoded) != value:
            raise ValueError("non-canonical base64url value")
        return decoded

    def encode(self, *, invitation_id: UUID, revision: int) -> str:
        payload = json.dumps(
            {"id": str(invitation_id), "revision": revision},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{self._encode(payload)}.{self._encode(signature)}"

    def decode(self, token: str) -> DecodedProjectInvitationToken | None:
        try:
            payload_value, signature_value = token.split(".", maxsplit=1)
            payload = self._decode(payload_value)
            signature = self._decode(signature_value)
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            value = json.loads(payload)
            invitation_id = UUID(str(value["id"]))
            revision = int(value["revision"])
            if revision < 1:
                return None
        except (
            binascii.Error,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None
        return DecodedProjectInvitationToken(
            invitation_id=invitation_id,
            revision=revision,
        )


__all__ = ["DecodedProjectInvitationToken", "ProjectInvitationTokenCodec"]
