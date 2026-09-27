from uuid import uuid4

import pytest
from pydantic import ValidationError

from scholens_job_contracts import JobResultManifest


def test_manifest_roundtrip_is_metadata_only_and_bound_to_content_and_generation():
    job_id = uuid4()
    digest = "a" * 64
    manifest = JobResultManifest(
        claim_generation=2,
        storage_key=f"jobs/results/{job_id}/2/{digest}.json",
        sha256=digest,
        byte_size=1024,
    )
    assert len(manifest.model_dump_json().encode()) < 512
    assert JobResultManifest.model_validate_json(manifest.model_dump_json()) == manifest
    for update in (
        {"claim_generation": 1},
        {"sha256": "b" * 64},
        {"storage_key": f"documents/{job_id}/source.pdf"},
        {"storage_key": f"jobs/results/{job_id}/2/../../private"},
        {"byte_size": 64 * 1024 * 1024 + 1},
        {"raw_content": "paper text"},
    ):
        with pytest.raises(ValidationError):
            JobResultManifest.model_validate({**manifest.model_dump(), **update})
