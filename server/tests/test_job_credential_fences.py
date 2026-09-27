import json
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import Request
import pytest

from app.transport.http.internal_v1.jobs_callbacks.credentials import (
    get_deepseek_credential,
    get_mineru_credential,
    get_zotero_credential,
)


@pytest.mark.parametrize(
    "handler,name",
    [
        (get_deepseek_credential, "deepseek"),
        (get_mineru_credential, "mineru"),
        (get_zotero_credential, "zotero"),
    ],
)
@pytest.mark.parametrize("generation", [None, 2])
def test_credential_lookup_is_inside_the_generation_fence(handler, name, generation):
    request = Request({"type": "http", "headers": []})
    request.state.verified_jobs_callback_body = json.dumps(
        {} if generation is None else {"claim_generation": generation}
    ).encode()
    capabilities, executor = MagicMock(), MagicMock()
    executor.query.side_effect = lambda fn: fn(capabilities)
    capabilities.job_results.require_transport.side_effect = RuntimeError(
        "expired or wrong generation"
    )
    job_id = uuid4()
    with pytest.raises(RuntimeError):
        handler(
            job_id=job_id, request=request, _verified=MagicMock(), executor=executor
        )
    getattr(capabilities, f"job_{name}_credential").assert_not_called()
    capabilities.job_results.require_transport.assert_called_once_with(
        job_id=job_id, generation=generation
    )
