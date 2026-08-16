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
