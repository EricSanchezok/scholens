from __future__ import annotations

from unittest.mock import patch

import pytest

from src.tasks import delete_storage_objects_task


def _document_key(index: int) -> str:
    return f"documents/{index:064x}/canonical.md"


def test_storage_delete_worker_validates_then_deletes_the_exact_batch() -> None:
    keys = [_document_key(1), _document_key(2)]
    with (
        patch("src.tasks._claim_job_with_retry", return_value=True) as claim,
        patch("src.tasks.s3_service.delete_file", return_value=True) as delete,
        patch("src.tasks._deliver_webhook", return_value=True) as deliver,
    ):
        result = delete_storage_objects_task.apply(
            args=(keys, "https://server.example/callback"),
            task_id="00000000-0000-4000-8000-000000000001",
            throw=True,
        ).get()

    claim.assert_called_once()
    assert [call.args[0] for call in delete.call_args_list] == keys
    assert deliver.call_args.args[1] == {
        "task_id": "00000000-0000-4000-8000-000000000001",
        "deleted_count": 2,
    }
    assert result["status"] == "completed"


@pytest.mark.parametrize(
    "keys",
    [
        [""],
        ["uploads/1/private/source.pdf"],
        ["documents/../private.pdf"],
        ["documents/evil\x00path.pdf"],
        [_document_key(2), _document_key(1)],
        [_document_key(1), _document_key(1)],
    ],
)
def test_storage_delete_worker_rejects_hostile_payload_before_claim_or_io(
    keys: list[str],
) -> None:
    with (
        patch("src.tasks._claim_job_with_retry") as claim,
        patch("src.tasks.s3_service.delete_file") as delete,
        patch("src.tasks._deliver_webhook") as deliver,
    ):
        with pytest.raises(ValueError, match="storage_delete"):
            delete_storage_objects_task.apply(
                args=(keys, "https://server.example/callback"),
                task_id="00000000-0000-4000-8000-000000000002",
                throw=True,
            ).get()

    claim.assert_not_called()
    delete.assert_not_called()
    deliver.assert_not_called()
