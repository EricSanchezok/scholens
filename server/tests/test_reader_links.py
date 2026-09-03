from __future__ import annotations

from uuid import uuid4

import pytest
from app.tooling.reader_links import build_reader_url, normalize_web_base_url


def test_build_reader_url_uses_project_context_when_present() -> None:
    document_id = uuid4()
    project_id = uuid4()

    assert build_reader_url(
        web_base_url="https://scholens.sanchezcloud.net/",
        document_id=document_id,
        project_id=project_id,
    ) == (
        f"https://scholens.sanchezcloud.net/reader/{document_id}?project={project_id}"
    )


def test_build_reader_url_omits_ambiguous_project_context() -> None:
    document_id = uuid4()

    assert (
        build_reader_url(
            web_base_url="http://127.0.0.1:7300",
            document_id=document_id,
        )
        == f"http://127.0.0.1:7300/reader/{document_id}"
    )


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "https://user:secret@scholens.example",
        "https://scholens.example/prefix",
        "https://scholens.example?redirect=elsewhere",
    ],
)
def test_reader_origin_rejects_non_origin_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_web_base_url(value)
