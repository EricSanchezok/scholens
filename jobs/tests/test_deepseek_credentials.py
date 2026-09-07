from unittest.mock import MagicMock
import asyncio
import pytest
from src import deepseek_credentials as credentials


def test_job_credential_is_scoped_and_never_uses_environment(monkeypatch):
    monkeypatch.setenv("SCHOLENS_AI_DEEPSEEK_API_KEY", "platform-key")
    response = MagicMock(status_code=200)
    response.json.return_value = {"credential": "owner-key"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(credentials, "post_signed_json", post)
    with pytest.raises(credentials.DeepSeekCredentialRequired):
        asyncio.run(credentials.current_deepseek_key())
    post.assert_not_called()
    with credentials.deepseek_job_context(
        "https://server/internal/v1/jobs/job-1/complete"
    ):
        assert asyncio.run(credentials.current_deepseek_key()) == "owner-key"
    assert (
        post.call_args.args[0]
        == "https://server/internal/v1/jobs/job-1/integration-credentials/deepseek"
    )
    response.close.assert_called_once()
    with pytest.raises(credentials.DeepSeekCredentialRequired):
        asyncio.run(credentials.current_deepseek_key())


def test_missing_job_key_returns_safe_error(monkeypatch):
    response = MagicMock(status_code=409)
    monkeypatch.setattr(
        credentials, "post_signed_json", MagicMock(return_value=response)
    )
    with credentials.deepseek_job_context(
        "https://server/internal/v1/jobs/job-1/complete"
    ):
        with pytest.raises(credentials.DeepSeekCredentialRequired):
            asyncio.run(credentials.current_deepseek_key())
    response.close.assert_called_once()
