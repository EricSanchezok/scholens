import hashlib
from uuid import uuid4

from app.modules.papers.infrastructure.models import Document
from app.modules.papers.application.contracts.extraction import (
    PaperMetadataExtraction,
    ResponseCitation,
)
from app.bootstrap.adapters.document_stage_callbacks import enrichment_update
from scholens_ai import evidence_segments


def test_enrichment_fills_gaps_and_preserves_manual_and_zotero_metadata():
    document = Document(
        title="Human title",
        original_filename="source.pdf",
        authors=["Zotero author"],
        summary="Human summary",
        raw_content="Source evidence.",
        field_provenance={"title": {"source": "manual"}},
    )
    metadata = PaperMetadataExtraction(
        title="AI title",
        authors=["AI author"],
        summary="AI summary",
        abstract="New abstract",
    )
    update = enrichment_update(document, metadata, job_id=uuid4())
    fields = update.model_dump(exclude_unset=True)
    assert "title" not in fields and "authors" not in fields and "summary" not in fields
    assert fields["abstract"] == "New abstract"
    assert fields["field_provenance"]["title"] == {"source": "manual"}


def test_only_a_recorded_filename_placeholder_can_be_replaced():
    metadata = PaperMetadataExtraction(title="Actual title")
    document = Document(
        title="source.pdf", original_filename="source.pdf", raw_content="text"
    )
    assert (
        "title"
        not in enrichment_update(document, metadata, job_id=uuid4()).model_fields_set
    )
    document.field_provenance = {"title": {"source": "filename"}}
    assert enrichment_update(document, metadata, job_id=uuid4()).title == "Actual title"


def test_summary_keeps_only_source_bound_verbatim_citations_and_valid_markers():
    text = "Actual supporting evidence."
    segment = next(iter(evidence_segments(text)))
    metadata = PaperMetadataExtraction(
        title="Title",
        summary="Claim.[^1] False.[^2] Mixed.[^1, ^2]",
        summary_citations=[
            ResponseCitation(
                text="Actual supporting evidence.", segment_id=segment.id, index=1
            ),
            ResponseCitation(
                text="Paraphrased evidence.", segment_id=segment.id, index=2
            ),
        ],
    )
    document = Document(
        title="Title",
        original_filename="source.pdf",
        raw_content=text,
        content_digest=hashlib.sha256(text.encode()).hexdigest(),
    )
    update = enrichment_update(document, metadata, job_id=uuid4())
    assert update.summary == "Claim.[^1] False. Mixed.[^1]"
    assert len(update.summary_citations) == 1
    assert update.summary_citations[0].text == text


def test_fenced_pdf_job_retains_a_small_audit_result_without_second_body_copy(
    monkeypatch,
):
    from unittest.mock import MagicMock
    from app.bootstrap.adapters.document_job_callback_support import (
        complete_pdf_job,
        job_repository,
    )
    from app.modules.jobs.application.contracts import PDFProcessingResult

    complete = MagicMock(return_value=(None, True))
    monkeypatch.setattr(job_repository, "complete", complete)
    result = PDFProcessingResult(
        success=True,
        job_id=str(uuid4()),
        raw_content="body",
        page_offset_map={1: [0, 4]},
        metadata=PaperMetadataExtraction(title="AI title"),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="fixture",
    )
    for compact in (False, True):
        assert complete_pdf_job(
            MagicMock(), job_id=uuid4(), result=result, compact=compact
        )
        stored = complete.call_args.kwargs["result"]
        assert stored["success"] is True
        assert ("raw_content" in stored) is not compact
        assert ("page_offset_map" in stored) is not compact
        assert ("metadata" in stored) is not compact
