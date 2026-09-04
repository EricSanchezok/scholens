from pathlib import Path
from unittest.mock import patch

import pytest

from src.s3_service import S3Service


def test_s3_service_requires_bucket_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)

    with pytest.raises(RuntimeError, match="S3_BUCKET_NAME must be configured"):
        S3Service()


def test_s3_service_builds_typed_client_from_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "scholens-test")

    with patch("src.s3_service.boto3.client") as client:
        service = S3Service()

    assert service.bucket_name == "scholens-test"
    client.assert_called_once()


def test_generated_artifacts_use_the_exact_idempotent_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "scholens-test")
    with patch("src.s3_service.boto3.client") as client_factory:
        service = S3Service()

    key = service.upload_bytes_to_key(
        b"canonical markdown",
        "uploads/pdf-parses/job-1/full.md",
        "text/markdown; charset=utf-8",
    )

    assert key == "uploads/pdf-parses/job-1/full.md"
    client_factory.return_value.put_object.assert_called_once_with(
        Bucket="scholens-test",
        Key=key,
        Body=b"canonical markdown",
        ContentType="text/markdown; charset=utf-8",
    )


def test_upload_file_uses_streaming_put_for_sha256_checked_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "scholens-test")
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.7\nsource")
    with patch("src.s3_service.boto3.client") as client_factory:
        service = S3Service()

        key = service.upload_file(
            str(source_path),
            "uploads/paper-ingestion/job-1/source.pdf",
            "application/pdf",
            checksum_sha256=("00" * 32),
        )

    assert key == "uploads/paper-ingestion/job-1/source.pdf"
    call = client_factory.return_value.put_object.call_args
    assert call is not None
    assert call.kwargs["Bucket"] == "scholens-test"
    assert call.kwargs["Key"] == key
    assert call.kwargs["ContentType"] == "application/pdf"
    assert call.kwargs["ContentLength"] == source_path.stat().st_size
    assert (
        call.kwargs["ChecksumSHA256"] == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )
    assert call.kwargs["Body"].name == str(source_path)
    assert call.kwargs["Body"].closed
    client_factory.return_value.upload_fileobj.assert_not_called()
