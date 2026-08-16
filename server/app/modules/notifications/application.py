"""Application contract for transactional product email."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TransactionalEmailMessage:
    subject: str
    html_body: str
    text_body: str


class EmailDeliveryError(RuntimeError):
    """A sanitized delivery failure with an explicit retry policy."""

    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


class TransactionalEmailSender(Protocol):
    async def send(
        self,
        *,
        to_address: str,
        message: TransactionalEmailMessage,
    ) -> None: ...


__all__ = [
    "EmailDeliveryError",
    "TransactionalEmailMessage",
    "TransactionalEmailSender",
]
