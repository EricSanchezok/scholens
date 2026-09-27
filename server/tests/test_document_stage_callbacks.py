from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from scholens_ai import TokenProjection

from app.bootstrap.adapters.document_stage_callbacks import (
    DocumentIndexCallback,
    DocumentIndexCompletion,
)


@pytest.mark.parametrize("missing_access", [False, True])
def test_index_result_is_access_fenced_and_does_not_change_document_readability(
    missing_access,
):
    job_id, doc_id = uuid4(), uuid4()
    job = SimpleNamespace(
        document_id=doc_id,
        payload={"content_digest": "a" * 64, "model_revision": "test-v1"},
    )
    callback = DocumentIndexCallback(
        task_id=job_id,
        projection=TokenProjection(
            content_digest="a" * 64, model_revision="test-v1", spans=[], vectors=""
        ),
    )
    db = MagicMock()
    db.scalar.return_value = None if missing_access else doc_id
    with (
        patch("app.bootstrap.adapters.document_stage_callbacks.job_repository") as jobs,
        patch(
            "app.bootstrap.adapters.document_stage_callbacks.TokenProjectionRepository"
        ) as projections,
    ):
        jobs.require.return_value = job
        result = DocumentIndexCompletion(db).complete(
            actor=SimpleNamespace(id=1),
            operation=MagicMock(),
            job_id=job_id,
            callback=callback,
        )
        assert result.value == {"accepted": not missing_access}
        if missing_access:
            projections.assert_not_called()
            jobs.fail.assert_called_once()
        else:
            projections.return_value.adopt.assert_called_once_with(
                document_id=doc_id, projection=callback.projection
            )
            jobs.complete.assert_called_once()
        db.add.assert_not_called()
