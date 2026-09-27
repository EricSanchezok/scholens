"""Fenced worker transport with durable results, independent of PDF/AI policy."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
import threading
import time
from typing import Any, Protocol
from uuid import UUID, uuid4

import requests
from celery import Task
from scholens_job_contracts import (
    EXECUTION_HEARTBEAT_SECONDS,
    JobExecutionClaim,
    JobResultManifest,
    JobResultReceipt,
    callback_json_bytes,
    require_callback_body_size,
)

from src.webhook_signing import post_signed_json

_execution_generation: ContextVar[int | None] = ContextVar(
    "job_execution_generation", default=None
)


@contextmanager
def execution_scope(generation: int | None) -> Iterator[None]:
    token = _execution_generation.set(generation)
    try:
        yield
    finally:
        _execution_generation.reset(token)


def execution_scope_payload() -> dict[str, int]:
    generation = _execution_generation.get()
    return {} if generation is None else {"claim_generation": generation}


_execution_runtime: ContextVar["FencedExecution | None"] = ContextVar(
    "fenced_execution_runtime", default=None
)


@contextmanager
def provider_effect_scope(execution: "FencedExecution") -> Iterator[None]:
    token = _execution_runtime.set(execution)
    try:
        yield
    finally:
        _execution_runtime.reset(token)


def begin_scoped_external_effect() -> None:
    runtime = _execution_runtime.get()
    if runtime is not None:
        runtime.begin_external_effect()


def current_execution() -> FencedExecution | None:
    return _execution_runtime.get()


class ResultStorage(Protocol):
    def object_exists(self, object_key: str) -> bool: ...
    def download_bounded_bytes(self, object_key: str, *, max_bytes: int) -> bytes: ...
    def upload_bytes_to_key(
        self, file_bytes: bytes, object_key: str, content_type: str
    ) -> str: ...


class DeliveryUnavailable(Exception):
    """Retry transport/replay only; do not turn known results into compute failure."""


class ExecutionLost(Exception):
    """A cancelled, expired, or superseded execution may produce no more effects."""


class ExecutionBusy(DeliveryUnavailable):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("job_execution_busy")
        self.retry_after_seconds = retry_after_seconds


class FencedExecution:
    def __init__(
        self,
        *,
        job_id: str,
        base_url: str,
        storage: ResultStorage,
        post: Callable[..., requests.Response] = post_signed_json,
        claim_token: UUID | None = None,
    ) -> None:
        self.job_id = str(UUID(job_id))
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith(f"/internal/v1/jobs/{self.job_id}"):
            raise ValueError("job_execution_url_mismatch")
        self._storage, self._post = storage, post
        self._claim_token = claim_token or uuid4()
        self.generation: int | None = None
        self.recover_only = False
        self._lease_seconds = 180
        self._last_success = time.monotonic()
        self._lost, self._stop = threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None
        self._progress_code = "downloading"
        self._delivered = False
        self._context_depth = 0

    @property
    def checkpoint_key(self) -> str:
        return f"jobs/checkpoints/{self.job_id}/result.json"

    @property
    def external_effect_key(self) -> str:
        return f"jobs/checkpoints/{self.job_id}/external-effect.json"

    def external_effect_started(self) -> bool:
        try:
            return self._storage.object_exists(self.external_effect_key)
        except Exception as exc:
            raise DeliveryUnavailable("job_external_effect_state_unavailable") from exc

    def _named_checkpoint_key(self, name: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) is None:
            raise ValueError("job_checkpoint_name_invalid")
        return f"jobs/checkpoints/{self.job_id}/{name}.json"

    def load_checkpoint(self, name: str, *, max_bytes: int) -> bytes | None:
        """Bounded opaque state; the operation owns validation and replay policy."""
        self.check_cancelled()
        key = self._named_checkpoint_key(name)
        try:
            data = (
                self._storage.download_bounded_bytes(key, max_bytes=max_bytes)
                if self._storage.object_exists(key)
                else None
            )
            if data is not None and len(data) > max_bytes:
                raise ValueError("job_checkpoint_oversized")
        except Exception as exc:
            raise DeliveryUnavailable("job_operation_checkpoint_unavailable") from exc
        self.check_cancelled()
        return data

    def save_checkpoint(self, name: str, data: bytes, *, max_bytes: int) -> None:
        self.check_cancelled()
        key = self._named_checkpoint_key(name)
        if len(data) > max_bytes:
            raise ValueError("job_checkpoint_oversized")
        try:
            self._storage.upload_bytes_to_key(data, key, "application/json")
        except Exception as exc:
            raise DeliveryUnavailable("job_operation_checkpoint_unavailable") from exc
        self.check_cancelled()

    def begin_external_effect(self) -> None:
        """Persist intent before a paid call, including same-generation retries.

        A provider success followed by failed result storage has an unknown
        outcome. Never turn that ambiguity into an automatic second paid call.
        """
        self.check_cancelled()
        if self.external_effect_started():
            raise DeliveryUnavailable("job_external_effect_already_started")
        try:
            self._storage.upload_bytes_to_key(
                callback_json_bytes({"claim_generation": self.generation}),
                self.external_effect_key,
                "application/json",
            )
        except Exception as exc:
            raise DeliveryUnavailable("job_external_effect_intent_unavailable") from exc
        self.check_cancelled()

    @property
    def claim_token(self) -> str:
        return str(self._claim_token)

    def _send(
        self, suffix: str, payload: dict[str, Any], *, timeout_seconds: int = 5
    ) -> dict[str, Any]:
        response = None
        try:
            response = self._post(
                self.base_url + suffix, payload, timeout=timeout_seconds
            )
            if response.status_code == 409:
                error = response.json()
                if (
                    isinstance(error, dict)
                    and error.get("code") == "job_execution_fence_rejected"
                ):
                    self._lost.set()
                    raise ExecutionLost("job_execution_lost")
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("job_receipt_invalid")
            return value
        except (requests.RequestException, ValueError) as exc:
            raise DeliveryUnavailable("job_receipt_unavailable") from exc
        finally:
            if response is not None:
                response.close()

    def claim(self) -> bool:
        result = JobExecutionClaim.model_validate(
            self._send("/execution/claim", {"claim_token": str(self._claim_token)})
        )
        if not result.claimed:
            if result.retry_after_seconds is not None:
                raise ExecutionBusy(result.retry_after_seconds)
            return False
        if result.claim_generation is None:
            raise DeliveryUnavailable("job_claim_generation_missing")
        self.generation, self.recover_only = (
            result.claim_generation,
            result.recover_only,
        )
        self._lease_seconds, self._last_success = result.lease_seconds, time.monotonic()
        return True

    def __enter__(self) -> FencedExecution:
        self.check_cancelled()
        self._context_depth += 1
        if self._context_depth > 1:
            return self
        self._thread = threading.Thread(
            target=self._heartbeat_loop, name=f"job-lease-{self.job_id}", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._context_depth -= 1
        if self._context_depth > 0:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6)

    def check_cancelled(self) -> None:
        if self.generation is None:
            raise RuntimeError("job_execution_not_claimed")
        if (
            self._lost.is_set()
            or time.monotonic() - self._last_success >= self._lease_seconds - 10
        ):
            self._lost.set()
            raise ExecutionLost("job_execution_lost")

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(EXECUTION_HEARTBEAT_SECONDS):
            try:
                self.report(self._progress_code)
            except DeliveryUnavailable:
                continue
            except ExecutionLost:
                return

    def report(self, progress_code: str) -> None:
        self.check_cancelled()
        self._progress_code = progress_code
        result = JobExecutionClaim.model_validate(
            self._send(
                "/execution/progress",
                {
                    "claim_generation": self.generation,
                    "progress": {"progress_code": progress_code},
                },
            )
        )
        if not result.claimed:
            if self._delivered:
                return
            self._lost.set()
            raise ExecutionLost("job_execution_lost")
        self._last_success = time.monotonic()

    def complete(
        self, payload: dict[str, Any], *, failure_code: str | None = None
    ) -> bool:
        self.check_cancelled()
        if str(payload.get("task_id")) != self.job_id:
            raise ValueError("job_result_identity_mismatch")
        data = callback_json_bytes(payload)
        require_callback_body_size(data)
        return self._persist_and_submit(data, failure_code=failure_code)

    def _persist_and_submit(self, data: bytes, *, failure_code: str | None) -> bool:
        self.check_cancelled()
        assert self.generation is not None
        digest = hashlib.sha256(data).hexdigest()
        manifest = JobResultManifest(
            claim_generation=self.generation,
            storage_key=f"jobs/results/{self.job_id}/{self.generation}/{digest}.json",
            sha256=digest,
            byte_size=len(data),
            failure_code=failure_code,
        )
        try:
            self._storage.upload_bytes_to_key(
                data, manifest.storage_key, "application/json"
            )
            # Publish the recovery pointer only after the immutable artifact exists.
            self._storage.upload_bytes_to_key(
                manifest.model_dump_json().encode(),
                self.checkpoint_key,
                "application/json",
            )
        except Exception as exc:
            raise DeliveryUnavailable("job_result_storage_unavailable") from exc
        self.check_cancelled()
        receipt = JobResultReceipt.model_validate(
            self._send("/results", manifest.model_dump(mode="json"))
        )
        if receipt.claim_generation != self.generation:
            raise DeliveryUnavailable("job_result_receipt_mismatch")
        if not receipt.accepted:
            self._lost.set()
            raise ExecutionLost("job_result_rejected")
        self._delivered = True
        self._stop.set()
        return True

    def resume_result(self) -> bool:
        """Replay completed work across generations without calling the provider."""
        self.check_cancelled()
        try:
            if not self._storage.object_exists(self.checkpoint_key):
                return False
            manifest = JobResultManifest.model_validate_json(
                self._storage.download_bounded_bytes(
                    self.checkpoint_key, max_bytes=4096
                )
            )
            if manifest.storage_key != manifest.key_for(UUID(self.job_id)):
                raise ValueError("job_checkpoint_identity_mismatch")
            data = self._storage.download_bounded_bytes(
                manifest.storage_key, max_bytes=manifest.byte_size
            )
            if (
                len(data) != manifest.byte_size
                or hashlib.sha256(data).hexdigest() != manifest.sha256
            ):
                raise ValueError("job_checkpoint_integrity_mismatch")
            payload = json.loads(data)
            if (
                not isinstance(payload, dict)
                or str(payload.get("task_id")) != self.job_id
            ):
                raise ValueError("job_checkpoint_payload_invalid")
        except Exception as exc:
            raise DeliveryUnavailable("job_checkpoint_unavailable") from exc
        return self._persist_and_submit(data, failure_code=manifest.failure_code)

    def fail(self, error_code: str) -> bool:
        return self.complete({"task_id": self.job_id}, failure_code=error_code)

    def source_ready(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.check_cancelled()
        return self._send(
            "/source-ready", {**payload, "claim_generation": self.generation}
        )

    def read_stage_input(self, suffix: str) -> dict[str, Any]:
        self.check_cancelled()
        result = self._send(
            suffix, {"claim_generation": self.generation}, timeout_seconds=35
        )
        self.check_cancelled()
        return result


def run_fenced_task(
    task: Task,
    *,
    callback_url: str,
    storage: ResultStorage,
    work: Callable[[FencedExecution], dict[str, Any]],
    resume_known_effect: Callable[[FencedExecution], bool] | None = None,
) -> dict[str, Any]:
    """One recovery policy for deterministic and paid worker operations."""
    headers = dict(task.request.headers or {})
    token = headers.get("execution_claim_token")
    runtime = FencedExecution(
        job_id=str(task.request.id),
        base_url=callback_url.rsplit("/", 1)[0],
        storage=storage,
        claim_token=UUID(token) if token else None,
    )
    try:
        if not runtime.claim():
            return {"task_id": runtime.job_id, "status": "duplicate"}
        with (
            runtime,
            execution_scope(runtime.generation),
            provider_effect_scope(runtime),
        ):
            if runtime.resume_result():
                return {"task_id": runtime.job_id, "status": "replayed"}
            if runtime.recover_only or runtime.external_effect_started():
                if resume_known_effect is None or not resume_known_effect(runtime):
                    runtime.fail("provider_outcome_unknown")
                    return {"task_id": runtime.job_id, "status": "failed"}
            result = work(runtime)
            return {
                "task_id": runtime.job_id,
                "status": result.get("status", "completed"),
            }
    except ExecutionLost:
        return {"task_id": runtime.job_id, "status": "cancelled"}
    except DeliveryUnavailable as exc:
        delay = exc.retry_after_seconds if isinstance(exc, ExecutionBusy) else 30
        raise task.retry(
            exc=exc,
            countdown=delay,
            max_retries=24,
            headers={**headers, "execution_claim_token": runtime.claim_token},
        ) from exc
