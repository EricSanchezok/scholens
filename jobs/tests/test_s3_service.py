from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.s3_service import S3Service


@pytest.mark.parametrize("failure", ["overflow", "read_error", "success"])
def test_bounded_download_always_closes_stream(failure: str) -> None:
    service = MagicMock(spec=S3Service)
    service.bucket_name = "test"
    service.s3_client = MagicMock()
    body = service.s3_client.get_object.return_value["Body"]
    body.read.return_value = b"abcde" if failure == "overflow" else b"abc"
    if failure == "read_error":
        body.read.side_effect = OSError("stream interrupted")
    if failure == "success":
        assert (
            S3Service.download_bounded_bytes(service, "result", max_bytes=4) == b"abc"
        )
    else:
        with pytest.raises((ValueError, OSError)):
            S3Service.download_bounded_bytes(service, "result", max_bytes=4)
    body.read.assert_called_once_with(5)
    body.close.assert_called_once()


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
