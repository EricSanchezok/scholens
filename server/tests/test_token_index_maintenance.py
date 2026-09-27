from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
import json

import pytest
from click.testing import CliRunner
from scholens_ai import EMBEDDING_MODEL_REVISION

from app.cli import cli
from app.operator_cli import maintenance
from app.operator_cli.token_indexes import build_repair_projection
from app.modules.papers.application.token_maintenance import (
    TokenIndexMaintenance,
    TokenIndexRepairPage,
    TokenIndexSource,
)
from app.shared.application import Actor
from app.shared.domain import AppError


def test_token_repair_requires_current_administrator():
    gateway = MagicMock()
    service = TokenIndexMaintenance(gateway, journal=MagicMock())
    with pytest.raises(AppError):
        service.source(
            actor=Actor(
                id=1, email="reader@example.com", status="active", email_verified=True
            ),
            document_id=uuid4(),
        )
    gateway.source.assert_not_called()


def test_token_repair_builds_exact_bilingual_projection_in_bounded_rpc_batches():
    class Tokenizer:
        def encode(self, sequence, **_):
            return SimpleNamespace(
                offsets=[(i, i + 1) for i, c in enumerate(sequence) if not c.isspace()]
            )

    model = MagicMock(revision=EMBEDDING_MODEL_REVISION)
    model.embed_passages.side_effect = lambda inputs: [
        [1.0] + [0.0] * 383 for _ in inputs
    ]
    source = "English 中文证据 and evidence.\n" * 100
    projection = build_repair_projection(source, model=model, tokenizer=Tokenizer())
    passages = projection.validated_passages(source)
    assert passages and passages[-1].end_offset == len(source.rstrip())
    assert max(len(call.args[0]) for call in model.embed_passages.call_args_list) <= 8


@pytest.mark.parametrize("apply", [False, True])
def test_token_repair_reads_one_body_and_computes_between_transactions(
    monkeypatch, apply
):
    events, document_id = [], uuid4()
    capabilities, runner = MagicMock(), MagicMock()
    capabilities.token_index_maintenance.candidates.return_value = TokenIndexRepairPage(
        1, (document_id,), 0, document_id
    )
    capabilities.token_index_maintenance.source.return_value = TokenIndexSource(
        document_id, "source"
    )
    capabilities.token_index_maintenance.apply_projection.return_value = True

    def query(callback):
        events.append("read_open")
        result = callback(capabilities)
        events.append("read_closed")
        return result

    def build(raw, **_):
        assert events[-1] == "read_closed" and raw == "source"
        events.append("compute")
        return MagicMock()

    def command(callback):
        assert events[-1] == "compute"
        events.append("write")
        return callback(capabilities)

    runner.query.side_effect, runner.command.side_effect = query, command
    monkeypatch.setattr(maintenance, "executor", lambda: runner)
    monkeypatch.setattr(maintenance, "load_user", lambda _: MagicMock(id=1))
    monkeypatch.setattr(maintenance, "current_admin", lambda *_: MagicMock())
    monkeypatch.setattr(
        maintenance,
        "configured_embedder",
        lambda: MagicMock(revision=EMBEDDING_MODEL_REVISION),
    )
    monkeypatch.setattr(maintenance, "load_passage_tokenizer", lambda: MagicMock())
    monkeypatch.setattr(maintenance, "build_repair_projection", build)
    args = [
        "maintenance",
        "backfill-token-indexes",
        "--actor-email",
        "admin@example.com",
        "--batch-size",
        "1",
        "--json",
    ]
    result = CliRunner().invoke(cli, args + (["--apply", "--yes"] if apply else []))
    assert result.exit_code == 0, result.output
    expected = ["read_open", "read_closed"]
    assert events == expected + (
        ["read_open", "read_closed", "compute", "write"] if apply else []
    )
    payload = json.loads(result.output)
    assert payload["indexed_documents"] == int(apply)
    assert payload["next_cursor"] == str(document_id)
