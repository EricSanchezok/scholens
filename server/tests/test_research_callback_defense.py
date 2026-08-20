"""Structural defense tests for research job completion callbacks.

A malformed task payload or a missing webhook result must fail the job and
still release its audio/background concurrency leases instead of raising
(which skips the post-commit and leaks leases until the TTL expires).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.jobs.application.callbacks import ReleaseJobConcurrency
from app.modules.jobs.application.contracts import (
    AudioOverviewWebhookData,
    DataTableWebhookData,
)
from app.modules.jobs.infrastructure.research_callbacks import (
    complete_audio_job,
    complete_data_table_job,
)
from app.shared.application import Actor
from app.shared.domain.enums import JobOperation


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _audio_job(
    job_id: object, payload: dict[str, object], user_id: int
) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        operation=JobOperation.AUDIO_GENERATE.value,
        requested_by_id=user_id,
        payload=payload,
    )


def _data_table_job(
    job_id: object, payload: dict[str, object], user_id: int
) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        operation=JobOperation.DATA_TABLE_GENERATE.value,
        requested_by_id=user_id,
        payload=payload,
    )


def _valid_audio_payload() -> dict[str, object]:
    return {
        "research_item_id": str(uuid4()),
        "scope_type": "document",
        "scope_id": str(uuid4()),
        "documents": [
            {
                "id": str(uuid4()),
                "title": "A paper",
                "canonical_s3_key": "documents/abc/source.pdf",
            }
        ],
        "length": "short",
    }


def _valid_data_table_payload() -> dict[str, object]:
    return {
        "research_item_id": str(uuid4()),
        "table": {
            "columns": ["title"],
            "papers": [
                {
                    "id": str(uuid4()),
                    "title": "A paper",
                    "raw_content": "content",
                }
            ],
        },
    }


def _releases(result: object) -> tuple[str, ...]:
    assert result.post_commit is not None
    return tuple(
        action.category
        for action in result.post_commit
        if isinstance(action, ReleaseJobConcurrency)
    )


@pytest.mark.asyncio
async def test_audio_callback_invalid_payload_fails_job_and_releases_both_leases() -> (
    None
):
    job_id = uuid4()
    actor = _actor()
    job = _audio_job(job_id, {"research_item_id": "not-a-uuid"}, actor.id)
    webhook = AudioOverviewWebhookData.model_construct(
        task_id=job_id,
        status="completed",
        result=None,
        usage_events=[],
    )
    fail_job = MagicMock(return_value=(SimpleNamespace(status="failed"), True))

    with (
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.fail",
            fail_job,
        ),
    ):
        result = await complete_audio_job(job_id, webhook, MagicMock())

    assert result.value.claimed is True
    assert fail_job.call_args.kwargs["error_code"] == "audio_callback_payload_invalid"
    assert _releases(result) == ("audio", "background")


@pytest.mark.asyncio
async def test_audio_callback_missing_result_fails_job_and_releases_both_leases() -> (
    None
):
    job_id = uuid4()
    actor = _actor()
    job = _audio_job(job_id, _valid_audio_payload(), actor.id)
    webhook = AudioOverviewWebhookData.model_construct(
        task_id=job_id,
        status="completed",
        result=None,
        usage_events=[],
    )
    fail_job = MagicMock(return_value=(SimpleNamespace(status="failed"), True))

    with (
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.fail",
            fail_job,
        ),
    ):
        result = await complete_audio_job(job_id, webhook, MagicMock())

    assert result.value.claimed is True
    assert fail_job.call_args.kwargs["error_code"] == "audio_callback_result_missing"
    assert _releases(result) == ("audio", "background")


@pytest.mark.asyncio
async def test_data_table_callback_invalid_payload_fails_job_and_releases_lease() -> (
    None
):
    job_id = uuid4()
    actor = _actor()
    job = _data_table_job(job_id, {"research_item_id": "not-a-uuid"}, actor.id)
    webhook = DataTableWebhookData.model_construct(
        task_id=job_id,
        status="completed",
        result=None,
        usage_events=[],
    )
    fail_job = MagicMock(return_value=(SimpleNamespace(status="failed"), True))

    with (
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.fail",
            fail_job,
        ),
    ):
        result = await complete_data_table_job(job_id, webhook, MagicMock())

    assert result.value.claimed is True
    assert (
        fail_job.call_args.kwargs["error_code"] == "data_table_callback_payload_invalid"
    )
    assert _releases(result) == ("background",)


@pytest.mark.asyncio
async def test_data_table_callback_missing_result_fails_job_and_releases_lease() -> (
    None
):
    job_id = uuid4()
    actor = _actor()
    job = _data_table_job(job_id, _valid_data_table_payload(), actor.id)
    webhook = DataTableWebhookData.model_construct(
        task_id=job_id,
        status="completed",
        result=None,
        usage_events=[],
    )
    fail_job = MagicMock(return_value=(SimpleNamespace(status="failed"), True))

    with (
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.modules.jobs.infrastructure.research_callbacks.job_repository.fail",
            fail_job,
        ),
    ):
        result = await complete_data_table_job(job_id, webhook, MagicMock())

    assert result.value.claimed is True
    assert (
        fail_job.call_args.kwargs["error_code"] == "data_table_callback_result_missing"
    )
    assert _releases(result) == ("background",)
