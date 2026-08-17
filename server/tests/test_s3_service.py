from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.helpers import s3 as s3_module
from app.helpers.s3 import (
    StagingObjectMetadata,
    document_archive_key,
    document_markdown_key,
    document_preview_key,
    document_source_key,
    s3_service,
)


def test_s3_client_uses_sigv4_virtual_hosted_urls() -> None:
    assert s3_service.s3_client.meta.config.signature_version == "s3v4"
    assert s3_service.s3_client.meta.config.s3["addressing_style"] == "virtual"


def test_canonical_upload_uses_the_configured_kms_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def put_object(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(s3_service.s3_client, "put_object", put_object)
    monkeypatch.setattr(s3_service, "bucket_name", "content-bucket")
    monkeypatch.setattr(s3_service, "kms_key_id", "content-key-arn")

    assert (
        s3_service.upload_bytes(
            object_key="documents/digest/source.pdf",
            data=b"%PDF",
            content_type="application/pdf",
        )
        == "documents/digest/source.pdf"
    )
    assert captured == {
        "Body": b"%PDF",
        "Bucket": "content-bucket",
        "ContentType": "application/pdf",
        "Key": "documents/digest/source.pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "content-key-arn",
    }


def test_presigned_url_keeps_the_provider_signed_host(monkeypatch) -> None:
    expected = (
        "https://bucket.s3.ap-southeast-1.amazonaws.com/uploads/paper.pdf"
        "?X-Amz-Signature=provider-signature"
    )

    def generate_presigned_url(*args, **kwargs) -> str:
        return expected

    monkeypatch.setattr(
        s3_service.s3_client,
        "generate_presigned_url",
        generate_presigned_url,
    )
    monkeypatch.setattr(s3_service, "bucket_name", "bucket")

    assert s3_service.generate_presigned_url("uploads/paper.pdf", 120) == expected


def test_staging_put_signs_pdf_content_type_and_checksum(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def generate_presigned_url(*args, **kwargs) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "https://uploads.example.test/source.pdf"

    monkeypatch.setattr(
        s3_service.s3_client,
        "generate_presigned_url",
        generate_presigned_url,
    )
    monkeypatch.setattr(s3_service, "bucket_name", "bucket")

    url, headers = s3_service.sign_put(
        object_key="uploads/7/session/source.pdf",
        size_bytes=42,
        checksum_sha256_base64="checksum",
        expires_in_seconds=900,
    )

    assert url == "https://uploads.example.test/source.pdf"
    assert headers == {
        "content-type": "application/pdf",
        "x-amz-checksum-sha256": "checksum",
    }
    assert captured["args"] == ("put_object",)
    assert captured["kwargs"] == {
        "Params": {
            "Bucket": "bucket",
            "Key": "uploads/7/session/source.pdf",
            "ContentType": "application/pdf",
            "ChecksumSHA256": "checksum",
        },
        "ExpiresIn": 900,
    }


def test_staging_metadata_requests_s3_checksum_validation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def head_object(**kwargs) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "ContentLength": 42,
            "ChecksumSHA256": "checksum",
            "ETag": '"etag"',
            "VersionId": "version-1",
        }

    monkeypatch.setattr(s3_service.s3_client, "head_object", head_object)
    monkeypatch.setattr(s3_service, "bucket_name", "bucket")

    assert s3_service.staging_object_metadata(
        "uploads/7/session/source.pdf"
    ) == StagingObjectMetadata(
        size_bytes=42,
        checksum_sha256="checksum",
        etag='"etag"',
        version_id="version-1",
    )
    assert captured == {
        "Bucket": "bucket",
        "Key": "uploads/7/session/source.pdf",
        "ChecksumMode": "ENABLED",
    }


def test_staging_download_is_version_locked_and_hard_bounded(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Body:
        def read(self, amount: int) -> bytes:
            captured["read_amount"] = amount
            return b"%PDF"

    def get_object(**kwargs) -> dict[str, object]:
        captured["request"] = kwargs
        return {"Body": Body()}

    monkeypatch.setattr(s3_service.s3_client, "get_object", get_object)
    monkeypatch.setattr(s3_service, "bucket_name", "bucket")
    metadata = StagingObjectMetadata(
        size_bytes=4,
        checksum_sha256="checksum",
        etag='"etag"',
        version_id="version-1",
    )

    assert (
        s3_service.download_staging_bytes(
            "uploads/7/session/source.pdf",
            metadata=metadata,
            max_bytes=30,
        )
        == b"%PDF"
    )
    assert captured == {
        "read_amount": 31,
        "request": {
            "Bucket": "bucket",
            "IfMatch": '"etag"',
            "Key": "uploads/7/session/source.pdf",
            "VersionId": "version-1",
        },
    }


def test_staging_download_records_sanitized_s3_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": "do not log diagnostics/uploads/private.pdf",
            },
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "GetObject",
    )
    metric = MagicMock()

    def get_object(**_kwargs: object) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(s3_service.s3_client, "get_object", get_object)
    monkeypatch.setattr(s3_service, "bucket_name", "private-bucket")
    monkeypatch.setattr(s3_module, "add_counter", metric)
    metadata = StagingObjectMetadata(
        size_bytes=4,
        checksum_sha256="checksum",
        etag='"etag"',
        version_id="version-1",
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="s3_staging_download_failed"),
    ):
        s3_service.download_staging_bytes(
            "uploads/7/session/source.pdf",
            metadata=metadata,
            max_bytes=30,
        )

    record = next(
        item
        for item in caplog.records
        if item.getMessage() == "s3.staging_object.download_failed"
    )
    assert getattr(record, "aws_error_code") == "AccessDenied"
    assert getattr(record, "aws_operation") == "GetObject"
    assert getattr(record, "aws_http_status") == 403
    assert "private-bucket" not in caplog.text
    assert "private.pdf" not in caplog.text
    metric.assert_called_once_with(
        "scholens.dependency.failures",
        attributes={"dependency": "s3"},
    )


def test_document_keys_are_content_addressed() -> None:
    digest = "a" * 64
    assert document_source_key(digest) == f"documents/{digest}/source.pdf"
    assert document_preview_key(digest) == f"documents/{digest}/preview.webp"
    assert document_markdown_key(digest) == f"documents/{digest}/canonical.md"
    assert document_archive_key(digest) == f"documents/{digest}/mineru-result.zip"
