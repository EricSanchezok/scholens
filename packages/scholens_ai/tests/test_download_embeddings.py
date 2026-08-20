from __future__ import annotations

from pathlib import Path

import pytest

from scholens_ai.download_embeddings import download_model


def test_download_model_rejects_an_empty_revision(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="revision must not be empty"):
        download_model(tmp_path / "model", revision="  ")
