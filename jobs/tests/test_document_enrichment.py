import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src import document_enrichment as module
from src.deepseek_credentials import DeepSeekCredentialRequired
from src.execution_delivery import DeliveryUnavailable
from src.schemas import PaperMetadataExtraction


@pytest.mark.parametrize(
    "outcome", ["success", "source_changed", "missing_key", "receipt_lost"]
)
def test_enrichment_is_optional_and_never_converts_delivery_loss_into_provider_failure(
    monkeypatch, outcome
):
    runtime, storage = MagicMock(), MagicMock()
    runtime.job_id = str(uuid4())
    source = b"Canonical evidence."
    storage.download_bounded_bytes.return_value = source
    extract = AsyncMock(return_value=PaperMetadataExtraction(title="Title"))
    if outcome == "missing_key":
        extract.side_effect = DeepSeekCredentialRequired()
    if outcome == "receipt_lost":
        runtime.complete.side_effect = DeliveryUnavailable()
    monkeypatch.setattr(module.llm_client, "extract_paper_metadata", extract)
    kwargs = dict(
        storage=storage,
        callback_url=f"https://server/internal/v1/jobs/{runtime.job_id}/complete",
        parser_markdown_s3_key="canonical.md",
        content_digest=hashlib.sha256(source).hexdigest()
        if outcome != "source_changed"
        else "a" * 64,
    )
    if outcome == "receipt_lost":
        with pytest.raises(DeliveryUnavailable):
            module.enrich_document(runtime, **kwargs)
        runtime.fail.assert_not_called()
    else:
        result = module.enrich_document(runtime, **kwargs)
        assert result["status"] == ("completed" if outcome == "success" else "failed")
    if outcome == "source_changed":
        extract.assert_not_called()
    else:
        assert extract.await_count == 1
        assert (
            extract.call_args.kwargs["before_provider"] == runtime.begin_external_effect
        )
    if outcome == "missing_key":
        runtime.fail.assert_called_once_with("deepseek_credential_required")
