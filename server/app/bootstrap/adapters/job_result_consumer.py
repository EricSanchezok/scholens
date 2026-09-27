"""One bounded Server-owned inbox consumer, with no work on the ASGI loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker
from scholens_observability import log_event

from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.modules.jobs.application.callbacks import JobCompletionResult
from app.modules.jobs.infrastructure.result_inbox import JobResultRepository
from scholens_job_contracts import JobResultManifest

logger = logging.getLogger(__name__)


class ResultArtifactReader(Protocol):
    def download_bounded_bytes(self, object_key: str, *, max_bytes: int) -> bytes: ...


def load_result(
    reader: ResultArtifactReader, manifest: JobResultManifest
) -> dict[str, object]:
    data = reader.download_bounded_bytes(
        manifest.storage_key, max_bytes=manifest.byte_size
    )
    if (
        len(data) != manifest.byte_size
        or hashlib.sha256(data).hexdigest() != manifest.sha256
    ):
        raise ValueError("Result artifact integrity mismatch")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("Result artifact must be an object")
    return payload


class JobResultConsumer:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        processor: JobCompletionProcessor,
        reader: ResultArtifactReader,
    ) -> None:
        self._sessions, self._processor, self._reader = sessions, processor, reader

    def drain_once(self) -> JobCompletionResult | None:
        with self._sessions() as db, db.begin():
            reservation = JobResultRepository(db).reserve_next()
        if reservation is None:
            return None
        try:
            # No Session remains open during storage transfer or decoding.
            payload = load_result(self._reader, reservation.manifest)
            return self._processor.apply_inbox(reservation, payload)
        except Exception as exc:
            result = self._processor.retry_inbox(
                reservation, error_code=type(exc).__name__
            )
            log_event(
                logger,
                logging.ERROR,
                "jobs.result.apply_failed",
                job_id=str(reservation.job_id),
                claim_generation=reservation.generation,
                error_code=type(exc).__name__,
            )
            return result

    async def run(self, stop: asyncio.Event) -> None:
        # At most one artifact and transaction per process; the database fence
        # coordinates replicas and recovers a consumer killed during apply.
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="job-results"
        ) as pool:
            loop = asyncio.get_running_loop()
            while not stop.is_set():
                try:
                    result = await loop.run_in_executor(pool, self.drain_once)
                    if result is not None:
                        await self._processor.finish_inbox(result)
                        continue
                except Exception as exc:
                    log_event(
                        logger,
                        logging.ERROR,
                        "jobs.result.consumer_failed",
                        error_code=type(exc).__name__,
                    )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
