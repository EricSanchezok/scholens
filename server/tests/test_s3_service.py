from __future__ import annotations

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


def test_document_keys_are_content_addressed() -> None:
    digest = "a" * 64
    assert document_source_key(digest) == f"documents/{digest}/source.pdf"
    assert document_preview_key(digest) == f"documents/{digest}/preview.webp"
    assert document_markdown_key(digest) == f"documents/{digest}/canonical.md"
    assert document_archive_key(digest) == f"documents/{digest}/mineru-result.zip"
