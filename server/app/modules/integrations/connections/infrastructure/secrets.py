"""Authenticated encryption for user-owned integration credentials."""

from __future__ import annotations

import base64
import os

from app.modules.integrations.connections.domain import IntegrationProvider
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"


class AesGcmIntegrationCredentialCipher:
    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as exc:
            raise ValueError(
                "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(key) != 32:
            raise ValueError(
                "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        self._cipher = AESGCM(key)

    def encrypt(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        plaintext: str,
    ) -> str:
        nonce = os.urandom(12)
        encrypted = self._cipher.encrypt(
            nonce,
            plaintext.encode(),
            _aad(user_id, provider),
        )
        payload = base64.urlsafe_b64encode(nonce + encrypted).decode().rstrip("=")
        return f"{_VERSION}.{payload}"

    def decrypt(
        self,
        *,
        user_id: int,
        provider: IntegrationProvider,
        ciphertext: str,
    ) -> str:
        try:
            version, payload = ciphertext.split(".", 1)
            if version != _VERSION:
                raise ValueError("unsupported credential version")
            padded = payload + "=" * (-len(payload) % 4)
            raw = base64.urlsafe_b64decode(padded)
            return self._cipher.decrypt(
                raw[:12],
                raw[12:],
                _aad(user_id, provider),
            ).decode()
        except Exception as exc:
            raise ValueError("integration credential decryption failed") from exc


def _aad(user_id: int, provider: IntegrationProvider) -> bytes:
    return f"scholens:integration:{_VERSION}:{user_id}:{provider.value}".encode()
