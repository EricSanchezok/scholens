import hashlib
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.adapters.job_result_consumer import load_result
from app.helpers.s3 import S3Service
from scholens_job_contracts import JobResultManifest


def test_result_loading_checks_exact_bytes_and_digest_before_application():
    payload = b'{"task_id":"test"}'
    digest = hashlib.sha256(payload).hexdigest()
    manifest = JobResultManifest(
        claim_generation=1,
        storage_key=f"jobs/results/{uuid4()}/1/{digest}.json",
        sha256=digest,
        byte_size=len(payload),
    )
    reader = MagicMock()
    reader.download_bounded_bytes.return_value = payload
    assert load_result(reader, manifest) == {"task_id": "test"}
    reader.download_bounded_bytes.assert_called_once_with(
        manifest.storage_key, max_bytes=len(payload)
    )
    for invalid in (payload[:-1], b"x" * len(payload)):
        reader.download_bounded_bytes.return_value = invalid
        with pytest.raises(ValueError, match="integrity"):
            load_result(reader, manifest)


def test_result_download_closes_the_stream_on_overflow():
    service = MagicMock(spec=S3Service)
    service.s3_client = MagicMock()
    body = service.s3_client.get_object.return_value = {"Body": MagicMock()}
    body["Body"].read.return_value = b"abcde"
    with pytest.raises(ValueError, match="bound"):
        S3Service.download_bounded_bytes(service, "jobs/results/object", max_bytes=4)
    body["Body"].read.assert_called_once_with(5)
    body["Body"].close.assert_called_once()
