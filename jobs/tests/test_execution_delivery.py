import hashlib
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests

from src.execution_delivery import DeliveryUnavailable, ExecutionLost, FencedExecution


def execution():
    job_id = uuid4()
    storage = MagicMock()
    storage.object_exists.return_value = False
    post = MagicMock()
    post.return_value.json.return_value = {"claimed": True, "claim_generation": 1}
    runtime = FencedExecution(
        job_id=str(job_id),
        base_url=f"https://server/internal/v1/jobs/{job_id}",
        storage=storage,
        post=post,
    )
    assert runtime.claim()
    return runtime, storage, post


def test_claim_response_loss_reuses_the_same_token():
    runtime, _, post = execution()
    token = post.call_args.args[1]["claim_token"]
    post.return_value.raise_for_status.side_effect = requests.ConnectionError()
    with pytest.raises(DeliveryUnavailable):
        runtime.claim()
    post.return_value.raise_for_status.side_effect = None
    assert runtime.claim()
    assert post.call_args.args[1]["claim_token"] == token


def test_result_receipt_contains_no_document_body_and_is_checkpointed_first():
    runtime, storage, post = execution()
    post.return_value.json.return_value = {"accepted": True, "claim_generation": 1}
    payload = {"task_id": runtime.job_id, "result": {"raw_content": "private paper"}}
    assert runtime.complete(payload)
    assert len(storage.upload_bytes_to_key.call_args_list) == 2
    artifact = storage.upload_bytes_to_key.call_args_list[0]
    receipt = post.call_args.args[1]
    assert receipt["sha256"] == hashlib.sha256(artifact.args[0]).hexdigest()
    assert receipt["byte_size"] == len(artifact.args[0])
    assert "private paper" not in json.dumps(receipt)
    assert post.call_args.args[0].endswith("/results")
    post.return_value.close.assert_called()


def test_receipt_response_loss_replays_persisted_result_in_new_generation():
    runtime, storage, post = execution()
    data = {"task_id": runtime.job_id, "result": {"metadata": "already paid"}}
    post.return_value.raise_for_status.side_effect = requests.ConnectionError()
    with pytest.raises(DeliveryUnavailable):
        runtime.complete(data)
    artifact, checkpoint = storage.upload_bytes_to_key.call_args_list
    storage.object_exists.return_value = True
    storage.download_bounded_bytes.side_effect = [checkpoint.args[0], artifact.args[0]]
    post.return_value.raise_for_status.side_effect = None
    post.return_value.json.return_value = {
        "claimed": True,
        "claim_generation": 2,
        "recover_only": True,
    }
    assert runtime.claim()
    assert runtime.recover_only
    post.return_value.json.return_value = {"accepted": True, "claim_generation": 2}
    assert runtime.resume_result()
    assert post.call_args.args[1]["claim_generation"] == 2
    assert storage.upload_bytes_to_key.call_args_list[-2].args[0] == artifact.args[0]


def test_corrupt_checkpoint_never_runs_or_submits_a_replacement_result():
    runtime, storage, post = execution()
    storage.object_exists.return_value = True
    storage.download_bounded_bytes.return_value = b'{"wrong":"checkpoint"}'
    post.reset_mock()
    with pytest.raises(DeliveryUnavailable):
        runtime.resume_result()
    storage.upload_bytes_to_key.assert_not_called()
    post.assert_not_called()


def test_lost_generation_stops_before_persisting_or_delivering():
    runtime, storage, post = execution()
    post.return_value.json.return_value = {"claimed": False}
    with pytest.raises(ExecutionLost):
        runtime.report("parsing")
    with pytest.raises(ExecutionLost):
        runtime.complete({"task_id": runtime.job_id})
    storage.upload_bytes_to_key.assert_not_called()


def test_failure_outcome_is_durable_without_using_an_unfenced_fail_callback():
    runtime, _, post = execution()
    post.return_value.json.return_value = {"accepted": True, "claim_generation": 1}
    assert runtime.fail("provider_outcome_unknown")
    assert post.call_args.args[1]["failure_code"] == "provider_outcome_unknown"
    assert post.call_args.args[0].endswith("/results")


@pytest.mark.parametrize("persisted", [False, True])
def test_paid_recovery_never_invokes_provider_work(persisted):
    from src.execution_delivery import run_fenced_task

    runtime = MagicMock()
    runtime.job_id = str(uuid4())
    runtime.claim.return_value = True
    runtime.resume_result.return_value = persisted
    runtime.recover_only = True
    task, work = MagicMock(), MagicMock()
    task.request.headers = {}
    with patch("src.execution_delivery.FencedExecution", return_value=runtime):
        result = run_fenced_task(
            task, callback_url="https://server/complete", storage=MagicMock(), work=work
        )
    work.assert_not_called()
    assert result["status"] == ("replayed" if persisted else "failed")
    if not persisted:
        runtime.fail.assert_called_once_with("provider_outcome_unknown")


def test_transport_retry_keeps_claim_identity_and_never_runs_work():
    from src.execution_delivery import run_fenced_task

    runtime = MagicMock()
    runtime.claim_token = str(uuid4())
    runtime.claim.side_effect = DeliveryUnavailable()
    task, work = MagicMock(), MagicMock()
    task.request.headers = {"trace": "kept"}
    task.retry.side_effect = RuntimeError("celery retry")
    with patch("src.execution_delivery.FencedExecution", return_value=runtime):
        with pytest.raises(RuntimeError, match="celery retry"):
            run_fenced_task(
                task,
                callback_url="https://server/complete",
                storage=MagicMock(),
                work=work,
            )
    work.assert_not_called()
    assert task.retry.call_args.kwargs["headers"] == {
        "trace": "kept",
        "execution_claim_token": runtime.claim_token,
    }


def test_unknown_paid_outcome_cannot_repeat_with_the_same_claim_generation():
    from src.execution_delivery import run_fenced_task

    runtime, storage, _post = execution()
    runtime.begin_external_effect()
    assert storage.upload_bytes_to_key.call_args.args[1] == runtime.external_effect_key
    # The provider returned, but result storage failed before result.json existed.
    # The retry retains generation 1; generation-only replay policy is insufficient.
    storage.object_exists.side_effect = lambda key: key == runtime.external_effect_key
    runtime.fail = MagicMock(return_value=True)
    task, work = MagicMock(), MagicMock()
    task.request.headers = {}
    with patch("src.execution_delivery.FencedExecution", return_value=runtime):
        result = run_fenced_task(
            task,
            callback_url=runtime.base_url + "/complete",
            storage=storage,
            work=work,
        )
    assert runtime.generation == 1
    assert result["status"] == "failed"
    runtime.fail.assert_called_once_with("provider_outcome_unknown")
    work.assert_not_called()


def test_external_effect_never_starts_when_intent_cannot_be_persisted():
    runtime, storage, _post = execution()
    storage.upload_bytes_to_key.side_effect = OSError("storage unavailable")
    with pytest.raises(DeliveryUnavailable):
        runtime.begin_external_effect()


def test_stage_read_stops_on_fence_rejection_and_closes_the_response():
    runtime, storage, post = execution()
    post.return_value.status_code = 409
    post.return_value.json.return_value = {"code": "job_execution_fence_rejected"}
    with pytest.raises(ExecutionLost):
        runtime.read_stage_input("/bibliography")
    with pytest.raises(ExecutionLost):
        runtime.begin_external_effect()
    storage.upload_bytes_to_key.assert_not_called()
    post.return_value.close.assert_called()


def test_stage_read_dependency_failure_retains_transport_retry():
    runtime, _, post = execution()
    post.return_value.status_code = 503
    post.return_value.raise_for_status.side_effect = requests.HTTPError()
    with pytest.raises(DeliveryUnavailable):
        runtime.read_stage_input("/bibliography")
    runtime.check_cancelled()
