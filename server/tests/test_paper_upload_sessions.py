from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4
from app.modules.papers.application.upload_sessions import (
    PaperUploadRecord,
    PaperUploadSessions,
    PreparePaperUploadRequest,
)
from app.shared.application import Actor


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class MemoryUploadGateway:
    def __init__(self) -> None:
        self.record: PaperUploadRecord | None = None
        self.cleanup_calls: list[tuple[datetime, int]] = []

    def create_or_refresh(self, **values: object) -> PaperUploadRecord:
        actor = values["actor"]
        request = values["request"]
        assert isinstance(actor, Actor)
        assert isinstance(request, PreparePaperUploadRequest)
        self.record = PaperUploadRecord(
            id=values["session_id"],
            actor_id=actor.id,
            project_id=request.project_id,
            filename=request.filename,
            size_bytes=request.size_bytes,
            sha256=request.sha256,
            object_key=str(values["object_key"]),
            status="prepared",
            expires_at=values["expires_at"],
            lease_expires_at=None,
            lease_token=None,
        )
        return self.record

    def claim(self, **values: object) -> PaperUploadRecord:
        assert self.record is not None
        self.record = replace(
            self.record,
            status="claimed",
            lease_expires_at=values["lease_expires_at"],
            lease_token=values["lease_token"],
        )
        return self.record

    def consume(self, **values: object) -> None:
        assert self.record is not None
        assert values["lease_token"] == self.record.lease_token
        self.record = replace(
            self.record,
            status="consumed",
            lease_expires_at=None,
            lease_token=None,
        )

    def release(self, **values: object) -> None:
        assert self.record is not None
        if values["lease_token"] != self.record.lease_token:
            return
        self.record = replace(
            self.record,
            status="failed" if values["failed"] else "prepared",
            lease_expires_at=None,
            lease_token=None,
        )

    def delete_expired(self, **values: object) -> int:
        now = values["now"]
        limit = values["limit"]
        assert isinstance(now, datetime)
        assert isinstance(limit, int)
        self.cleanup_calls.append((now, limit))
        return 0


class RecordingUploadStore:
    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None

    def sign_put(self, **values: object) -> tuple[str, dict[str, str]]:
        self.arguments = values
        return "https://uploads.example.test/source.pdf", {
            "content-type": "application/pdf",
            "x-amz-checksum-sha256": str(values["checksum_sha256_base64"]),
        }


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def test_prepare_upload_returns_bounded_session_and_exact_checksum_headers() -> None:
    now = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    gateway = MemoryUploadGateway()
    store = RecordingUploadStore()
    sessions = PaperUploadSessions(
        gateway=gateway,
        store=store,
        clock=FixedClock(now),
    )
    checksum = "ab" * 32

    prepared = sessions.prepare(
        actor=_actor(),
        request=PreparePaperUploadRequest(
            filename="chain-of-thought.pdf",
            size_bytes=42,
            sha256=checksum,
        ),
    )

    assert prepared.method == "PUT"
    assert prepared.upload_url_expires_at.isoformat() == "2026-08-16T09:15:00+00:00"
    assert prepared.session_expires_at.isoformat() == "2026-08-17T09:00:00+00:00"
    assert prepared.headers == {
        "content-type": "application/pdf",
        "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(checksum)).decode(),
    }
    assert gateway.record is not None
    assert gateway.record.object_key == (
        f"uploads/{_actor().id}/{prepared.upload_id}/source.pdf"
    )
    assert store.arguments == {
        "object_key": gateway.record.object_key,
        "size_bytes": 42,
        "checksum_sha256_base64": prepared.headers["x-amz-checksum-sha256"],
        "expires_in_seconds": 900,
    }
    assert gateway.cleanup_calls == [(now, 100)]


def test_upload_lifecycle_delegates_claim_consume_and_retryable_release() -> None:
    now = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    gateway = MemoryUploadGateway()
    sessions = PaperUploadSessions(
        gateway=gateway,
        store=RecordingUploadStore(),
        clock=FixedClock(now),
    )
    prepared = sessions.prepare(
        actor=_actor(),
        request=PreparePaperUploadRequest(
            filename="paper.pdf",
            size_bytes=10,
            sha256="01" * 32,
        ),
    )

    claimed = sessions.claim(actor=_actor(), upload_id=prepared.upload_id)
    assert claimed.status == "claimed"
    assert claimed.lease_expires_at is not None
    assert claimed.lease_token is not None

    sessions.release(
        actor=_actor(),
        upload_id=prepared.upload_id,
        lease_token=claimed.lease_token,
        failed=False,
    )
    assert gateway.record is not None
    assert gateway.record.status == "prepared"

    claimed = sessions.claim(actor=_actor(), upload_id=prepared.upload_id)
    assert claimed.lease_token is not None
    sessions.consume(
        actor=_actor(),
        upload_id=prepared.upload_id,
        lease_token=claimed.lease_token,
    )
    assert gateway.record.status == "consumed"


def test_stale_upload_lease_cannot_release_a_new_claim() -> None:
    now = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    gateway = MemoryUploadGateway()
    sessions = PaperUploadSessions(
        gateway=gateway,
        store=RecordingUploadStore(),
        clock=FixedClock(now),
    )
    prepared = sessions.prepare(
        actor=_actor(),
        request=PreparePaperUploadRequest(
            filename="paper.pdf", size_bytes=10, sha256="01" * 32
        ),
    )
    first = sessions.claim(actor=_actor(), upload_id=prepared.upload_id)
    second = gateway.claim(
        actor=_actor(),
        upload_id=prepared.upload_id,
        lease_token=uuid4(),
        lease_expires_at=now,
        now=now,
    )
    assert first.lease_token is not None

    sessions.release(
        actor=_actor(),
        upload_id=prepared.upload_id,
        lease_token=first.lease_token,
        failed=False,
    )

    assert gateway.record == second


def test_prepare_request_never_accepts_a_local_path_as_filename() -> None:
    request_error = None
    try:
        PreparePaperUploadRequest(
            filename="/private/research/paper.pdf",
            size_bytes=10,
            sha256="01" * 32,
        )
    except ValueError as exc:
        request_error = exc

    assert request_error is not None
