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


def test_result_download_uses_cancellable_bounded_transfer():
    from unittest.mock import AsyncMock

    service = MagicMock(spec=S3Service)
    transfer = service._transfers.return_value
    transfer.read = AsyncMock(side_effect=ValueError("s3_object_byte_bound_exceeded"))
    with pytest.raises(ValueError, match="bound"):
        S3Service.download_bounded_bytes(service, "jobs/results/object", max_bytes=4)
    transfer.read.assert_awaited_once_with("jobs/results/object", max_bytes=4)
