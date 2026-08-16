from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from Tea.exceptions import TeaException

import app.database.models  # noqa: F401 -- register every relationship target
from app.modules.notifications.application import (
    EmailDeliveryError,
    TransactionalEmailMessage,
)
from app.modules.notifications.infrastructure.aliyun import (
    AliyunTransactionalEmailSender,
)
from app.modules.projects.application.invitation_tokens import (
    ProjectInvitationTokenCodec,
)
from app.modules.projects.infrastructure.invitation_delivery import (
    ProjectInvitationDeliveryRepository,
    ProjectInvitationDeliverySupervisor,
    ReservedProjectInvitationDelivery,
)
from app.modules.projects.infrastructure.invitation_email import (
    build_project_invitation_email,
)

TOKEN_SECRET = "project-invitation-test-secret-32-bytes"


def test_invitation_token_is_tamper_evident_and_revisioned() -> None:
    codec = ProjectInvitationTokenCodec(TOKEN_SECRET)
    invitation_id = uuid4()
    first = codec.encode(invitation_id=invitation_id, revision=1)
    second = codec.encode(invitation_id=invitation_id, revision=2)

    decoded_first = codec.decode(first)
    decoded_second = codec.decode(second)
    assert decoded_first is not None
    assert decoded_second is not None
    assert decoded_first.invitation_id == invitation_id
    assert decoded_first.revision == 1
    assert decoded_second.revision == 2
    assert codec.decode(f"{first[:-1]}x") is None
    assert codec.decode("not-a-token") is None
    assert codec.decode("x" * 513) is None
    with pytest.raises(ValueError, match="positive integer"):
        codec.encode(invitation_id=invitation_id, revision=0)


def test_invitation_token_rejects_an_extra_segment() -> None:
    codec = ProjectInvitationTokenCodec(TOKEN_SECRET)
    invitation_id = uuid4()
    valid = codec.encode(invitation_id=invitation_id, revision=1)
    payload_value, signature_value = valid.split(".")

    assert codec.decode(f"{payload_value}.{signature_value}.extra") is None


@pytest.mark.parametrize(
    "payload",
    [
        {"id": str(uuid4()), "revision": True},
        {"id": str(uuid4()), "revision": 1, "unexpected": "field"},
    ],
)
def test_invitation_token_rejects_noncanonical_signed_payload(
    payload: dict[str, object],
) -> None:
    codec = ProjectInvitationTokenCodec(TOKEN_SECRET)
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(TOKEN_SECRET.encode(), raw_payload, hashlib.sha256).digest()
    token = f"{codec._encode(raw_payload)}.{codec._encode(signature)}"

    assert codec.decode(token) is None


def test_project_invitation_email_escapes_content_and_has_equivalent_text() -> None:
    message = build_project_invitation_email(
        inviter_name='<Admin "One">',
        project_title="A <script>alert(1)</script>",
        invitation_token="signed.token",
        client_domain="https://scholens.example/",
    )

    expected_url = "https://scholens.example/project-invitations/signed.token"
    assert expected_url in message.html_body
    assert expected_url in message.text_body
    assert "<script>" not in message.html_body
    assert "&lt;script&gt;" in message.html_body
    assert "A <script>alert(1)</script>" in message.text_body

    sanitized = build_project_invitation_email(
        inviter_name="Header\r\nInjection",
        project_title="Project",
        invitation_token="signed.token",
        client_domain="https://scholens.example",
    )
    assert "\r" not in sanitized.subject
    assert "\n" not in sanitized.subject

    bounded = build_project_invitation_email(
        inviter_name="A" * 500,
        project_title="Project",
        invitation_token="signed.token",
        client_domain="https://scholens.example",
    )
    assert len(bounded.subject) <= 100


def test_project_invitation_email_rejects_relative_client_domain() -> None:
    with pytest.raises(ValueError, match="CLIENT_DOMAIN"):
        build_project_invitation_email(
            inviter_name="Admin",
            project_title="Project",
            invitation_token="signed.token",
            client_domain="/relative",
        )


@pytest.mark.parametrize(
    "client_domain",
    [
        "https://user:secret@scholens.example",
        "https://scholens.example/product",
        "https://scholens.example?source=email",
        "https://scholens.example:invalid",
    ],
)
def test_project_invitation_email_rejects_non_origin_client_domain(
    client_domain: str,
) -> None:
    with pytest.raises(ValueError, match="CLIENT_DOMAIN"):
        build_project_invitation_email(
            inviter_name="Admin",
            project_title="Project",
            invitation_token="signed.token",
            client_domain=client_domain,
        )


@pytest.mark.asyncio
async def test_aliyun_sender_sets_bounded_runtime_and_both_bodies() -> None:
    client = MagicMock()
    client.single_send_mail_with_options_async = MagicMock(return_value=None)

    async def send(request: object, runtime: object) -> None:
        client.request = request
        client.runtime = runtime

    client.single_send_mail_with_options_async.side_effect = send
    sender = AliyunTransactionalEmailSender(
        access_key_id="key",
        access_key_secret="secret",
        account_name="sender@example.com",
        from_alias="Scholens",
        reply_to_address=True,
        client=client,
    )
    message = TransactionalEmailMessage(
        subject="Subject",
        html_body="<p>Body</p>",
        text_body="Body",
    )

    await sender.send(to_address="reader@example.com", message=message)

    assert client.request.to_address == "reader@example.com"
    assert client.request.html_body == "<p>Body</p>"
    assert client.request.text_body == "Body"
    assert client.request.address_type == 1
    assert client.request.click_trace == "0"
    assert client.runtime.autoretry is False
    assert client.runtime.connect_timeout == 5_000
    assert client.runtime.read_timeout == 30_000


@pytest.mark.asyncio
async def test_aliyun_sender_sanitizes_unknown_provider_failure() -> None:
    client = MagicMock()

    async def fail(_request: object, _runtime: object) -> None:
        raise OSError("provider response must not escape")

    client.single_send_mail_with_options_async.side_effect = fail
    sender = AliyunTransactionalEmailSender(
        access_key_id="key",
        access_key_secret="secret",
        account_name="sender@example.com",
        from_alias="Scholens",
        reply_to_address=True,
        client=client,
    )

    with pytest.raises(EmailDeliveryError) as exc_info:
        await sender.send(
            to_address="reader@example.com",
            message=TransactionalEmailMessage("Subject", "HTML", "Text"),
        )

    assert exc_info.value.code == "provider_unavailable"
    assert exc_info.value.transient is True
    assert "provider response" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("provider_code", "status_code", "expected_code", "transient"),
    [
        ("Throttling.User", 429, "provider_throttled", True),
        ("InternalError", 503, "provider_unavailable", True),
        ("InvalidAddress", 400, "provider_rejected", False),
    ],
)
@pytest.mark.asyncio
async def test_aliyun_sender_classifies_provider_failures(
    provider_code: str,
    status_code: int,
    expected_code: str,
    transient: bool,
) -> None:
    client = MagicMock()

    async def fail(_request: object, _runtime: object) -> None:
        raise TeaException({"code": provider_code, "data": {"statusCode": status_code}})

    client.single_send_mail_with_options_async.side_effect = fail
    sender = AliyunTransactionalEmailSender(
        access_key_id="key",
        access_key_secret="secret",
        account_name="sender@example.com",
        from_alias="Scholens",
        reply_to_address=True,
        client=client,
    )

    with pytest.raises(EmailDeliveryError) as exc_info:
        await sender.send(
            to_address="reader@example.com",
            message=TransactionalEmailMessage("Subject", "HTML", "Text"),
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.transient is transient


def test_delivery_claim_uses_skip_locked() -> None:
    db = MagicMock(spec=Session)
    rows = MagicMock()
    rows.all.return_value = []
    db.scalars.return_value = rows

    ProjectInvitationDeliveryRepository().reserve(
        db,
        now=datetime.now(UTC),
        lease=timedelta(seconds=30),
        limit=20,
    )

    statement = db.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_expired_lease_recovery_marks_exhausted_delivery_failed() -> None:
    db = MagicMock(spec=Session)
    exhausted = MagicMock(rowcount=1)
    recoverable = MagicMock(rowcount=2)
    db.execute.side_effect = [exhausted, recoverable]

    recovered = ProjectInvitationDeliveryRepository().recover_expired_leases(
        db,
        now=datetime.now(UTC),
    )

    statements = [call.args[0] for call in db.execute.call_args_list]
    exhausted_sql = str(statements[0].compile(dialect=postgresql.dialect()))
    recoverable_sql = str(statements[1].compile(dialect=postgresql.dialect()))
    assert recovered == 3
    assert "delivery_attempt_count >=" in exhausted_sql
    assert "delivery_attempt_count <" in recoverable_sql
    assert "failed" in statements[0].compile().params.values()


@pytest.mark.parametrize(
    ("attempt_count", "transient"),
    [(1, False), (8, True)],
)
def test_delivery_failure_becomes_terminal_for_rejection_or_exhaustion(
    attempt_count: int,
    transient: bool,
) -> None:
    db = MagicMock(spec=Session)
    db.execute.return_value.rowcount = 1
    delivery = ReservedProjectInvitationDelivery(
        invitation_id=uuid4(),
        token_revision=1,
        lease_id=uuid4(),
        attempt_count=attempt_count,
        enqueued_at=datetime.now(UTC),
        recipient_email="reader@example.com",
        inviter_name="Owner",
        project_title="Research Project",
    )

    changed, status = ProjectInvitationDeliveryRepository().fail(
        db,
        delivery=delivery,
        error=EmailDeliveryError("provider_rejected", transient=transient),
        next_attempt_at=datetime.now(UTC),
    )

    assert changed is True
    assert status == "failed"


class _Sender:
    def __init__(self, error: EmailDeliveryError | None = None) -> None:
        self.error = error
        self.messages: list[TransactionalEmailMessage] = []

    async def send(
        self,
        *,
        to_address: str,
        message: TransactionalEmailMessage,
    ) -> None:
        assert to_address == "reader@example.com"
        self.messages.append(message)
        if self.error is not None:
            raise self.error


def _reserved() -> ReservedProjectInvitationDelivery:
    return ReservedProjectInvitationDelivery(
        invitation_id=uuid4(),
        token_revision=1,
        lease_id=uuid4(),
        attempt_count=1,
        enqueued_at=datetime.now(UTC),
        recipient_email="reader@example.com",
        inviter_name="Owner",
        project_title="Research Project",
    )


@pytest.mark.asyncio
async def test_supervisor_records_success_outside_the_claim_transaction() -> None:
    sender = _Sender()
    delivery = _reserved()
    supervisor = ProjectInvitationDeliverySupervisor(
        session_factory=MagicMock(),
        sender=sender,
        token_codec=ProjectInvitationTokenCodec(TOKEN_SECRET),
        client_domain="https://scholens.example",
    )
    supervisor._reserve = MagicMock(return_value=(delivery,))  # type: ignore[method-assign]
    supervisor._active = MagicMock(return_value=True)  # type: ignore[method-assign]
    supervisor._complete = MagicMock(return_value=True)  # type: ignore[method-assign]

    assert await supervisor.deliver_once() == 1
    assert len(sender.messages) == 1
    supervisor._complete.assert_called_once_with(delivery)


@pytest.mark.asyncio
async def test_supervisor_does_not_send_an_inactive_invitation() -> None:
    sender = _Sender()
    delivery = _reserved()
    supervisor = ProjectInvitationDeliverySupervisor(
        session_factory=MagicMock(),
        sender=sender,
        token_codec=ProjectInvitationTokenCodec(TOKEN_SECRET),
        client_domain="https://scholens.example",
    )
    supervisor._reserve = MagicMock(return_value=(delivery,))  # type: ignore[method-assign]
    supervisor._active = MagicMock(return_value=False)  # type: ignore[method-assign]

    assert await supervisor.deliver_once() == 0
    assert sender.messages == []


@pytest.mark.asyncio
async def test_supervisor_persists_retry_without_leaking_provider_detail() -> None:
    error = EmailDeliveryError("provider_throttled", transient=True)
    sender = _Sender(error)
    delivery = _reserved()
    supervisor = ProjectInvitationDeliverySupervisor(
        session_factory=MagicMock(),
        sender=sender,
        token_codec=ProjectInvitationTokenCodec(TOKEN_SECRET),
        client_domain="https://scholens.example",
    )
    supervisor._reserve = MagicMock(return_value=(delivery,))  # type: ignore[method-assign]
    supervisor._active = MagicMock(return_value=True)  # type: ignore[method-assign]
    supervisor._fail = MagicMock(return_value=(True, "pending"))  # type: ignore[method-assign]

    assert await supervisor.deliver_once() == 0
    supervisor._fail.assert_called_once_with(delivery, error)


def test_supervisor_rejects_a_lease_shorter_than_provider_timeouts() -> None:
    with pytest.raises(ValueError, match="exceed provider timeouts"):
        ProjectInvitationDeliverySupervisor(
            session_factory=MagicMock(),
            sender=_Sender(),
            token_codec=ProjectInvitationTokenCodec(TOKEN_SECRET),
            client_domain="https://scholens.example",
            delivery_lease=timedelta(seconds=39),
        )
