"""Guarded product maintenance commands."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast
from uuid import UUID

import click
from scholens_ai import EMBEDDING_MODEL_REVISION, try_local_embedder

from app.modules.reading_activity.application import ReadingActivityRetentionResult
from app.modules.papers.application.maintenance import PassageEmbeddingWrite
from app.operator_cli.common import (
    CliState,
    OutputGroup,
    cli_operation,
    confirm,
    current_admin,
    email_callback,
    emit,
    executor,
    guarded,
    load_user,
)


MAX_READING_RETENTION_BATCHES_PER_INVOCATION = 1000


@click.group("maintenance", cls=OutputGroup)
def maintenance_group() -> None:
    """Run narrowly scoped maintenance through application services."""


@maintenance_group.command("backfill-passages")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 5000),
    default=100,
    show_default=True,
    help="Maximum documents processed in this invocation and transaction.",
)
@click.option(
    "--apply", is_flag=True, help="Apply changes; otherwise only count candidates."
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def backfill_passages(
    state: CliState,
    actor_email: str,
    batch_size: int,
    apply: bool,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    if apply:
        confirm("Backfill missing document passages?", yes=yes)
    invoke = executor().command if apply else executor().query
    result = invoke(
        lambda capabilities: capabilities.passage_maintenance.backfill_passages(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("maintenance.backfill-passages"),
            batch_size=batch_size,
            apply=apply,
        )
    )
    payload = {
        "status": "changed" if result.indexed_documents else "unchanged",
        "dry_run": not apply,
        "candidates": result.candidates,
        "indexed_documents": result.indexed_documents,
        "indexed_passages": result.indexed_passages,
    }
    emit(state, payload)


@maintenance_group.command("backfill-passage-embeddings")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 512),
    default=128,
    show_default=True,
    help="Maximum passages embedded outside a database transaction.",
)
@click.option(
    "--apply", is_flag=True, help="Apply changes; otherwise only count candidates."
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def backfill_passage_embeddings(
    state: CliState,
    actor_email: str,
    batch_size: int,
    apply: bool,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    snapshot = executor().query(
        lambda capabilities: (
            capabilities.passage_maintenance.passage_embedding_candidates(
                actor=current_admin(capabilities, actor_user.id),
                batch_size=batch_size,
            )
        )
    )
    if not apply or not snapshot.items:
        emit(
            state,
            {
                "status": "unchanged",
                "dry_run": not apply,
                "candidates": snapshot.candidates,
                "indexed_passages": 0,
                "stale_passages": 0,
            },
        )
        return
    confirm("Backfill local passage-search embeddings?", yes=yes)
    embedder = try_local_embedder()
    if embedder is None:
        raise click.ClickException("Local embedding model is not configured.")
    embeddings = embedder.embed_passages(
        [candidate.content for candidate in snapshot.items]
    )
    records = tuple(
        PassageEmbeddingWrite(
            passage_id=candidate.passage_id,
            document_id=candidate.document_id,
            start_line=candidate.start_line,
            source_digest=candidate.source_digest,
            embedding=tuple(embedding),
        )
        for candidate, embedding in zip(snapshot.items, embeddings, strict=True)
    )
    result = executor().command(
        lambda capabilities: capabilities.passage_maintenance.apply_passage_embeddings(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("maintenance.backfill-passage-embeddings"),
            candidates=snapshot.candidates,
            records=records,
            model_revision=EMBEDDING_MODEL_REVISION,
        )
    )
    emit(
        state,
        {
            "status": "changed" if result.indexed_passages else "unchanged",
            "dry_run": False,
            "candidates": result.candidates,
            "indexed_passages": result.indexed_passages,
            "stale_passages": result.stale_passages,
        },
    )


@maintenance_group.command("purge-reading-session-pages")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--retention-days",
    type=click.IntRange(1, 90),
    default=90,
    show_default=True,
    help="Maximum age of fine-grained page trajectories.",
)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 100),
    default=100,
    show_default=True,
    help="Maximum sessions considered per transaction (also page-row budgeted).",
)
@click.option(
    "--apply", is_flag=True, help="Apply deletion; otherwise only count candidates."
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def purge_reading_session_pages(
    state: CliState,
    actor_email: str,
    retention_days: int,
    batch_size: int,
    apply: bool,
    yes: bool,
) -> None:
    """Enforce the fine-grained reading trajectory retention ceiling."""
    actor_user = load_user(actor_email)
    if apply:
        confirm("Permanently purge expired reading session page detail?", yes=yes)

    def purge_batch() -> ReadingActivityRetentionResult:
        runner = executor()
        invoke = runner.command if apply else runner.query
        return cast(
            ReadingActivityRetentionResult,
            invoke(
                lambda capabilities: (
                    capabilities.reading_activity_retention.purge_session_pages(
                        actor=current_admin(capabilities, actor_user.id),
                        operation=cli_operation(
                            "maintenance.purge-reading-session-pages"
                        ),
                        retention_days=retention_days,
                        batch_size=batch_size,
                        apply=apply,
                    )
                )
            ),
        )

    result = purge_batch()
    initial_candidates = result.candidates
    total_purged_sessions = result.purged_sessions
    total_purged_pages = result.purged_pages
    if apply:
        for _ in range(MAX_READING_RETENTION_BATCHES_PER_INVOCATION - 1):
            if result.candidates <= result.purged_sessions:
                break
            if result.purged_sessions == 0:
                raise RuntimeError("reading_activity_retention_drain_stalled")
            result = purge_batch()
            total_purged_sessions += result.purged_sessions
            total_purged_pages += result.purged_pages
        else:
            if result.candidates > result.purged_sessions:
                raise RuntimeError("reading_activity_retention_drain_incomplete")
    emit(
        state,
        {
            "status": "changed" if total_purged_sessions else "unchanged",
            "dry_run": not apply,
            "cutoff": result.cutoff.isoformat(),
            "candidates": initial_candidates,
            "purged_sessions": total_purged_sessions,
            "purged_pages": total_purged_pages,
        },
    )


@maintenance_group.command("backfill-search-embeddings")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 1000),
    default=100,
    show_default=True,
    help="Maximum documents embedded in this invocation and transaction.",
)
@click.option(
    "--apply", is_flag=True, help="Apply changes; otherwise only count candidates."
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def backfill_search_embeddings(
    state: CliState,
    actor_email: str,
    batch_size: int,
    apply: bool,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    if apply:
        confirm("Backfill local semantic-search embeddings?", yes=yes)
    invoke = executor().command if apply else executor().query
    result = invoke(
        lambda capabilities: (
            capabilities.search_embedding_maintenance.backfill_search_embeddings(
                actor=current_admin(capabilities, actor_user.id),
                operation=cli_operation("maintenance.backfill-search-embeddings"),
                batch_size=batch_size,
                apply=apply,
            )
        )
    )
    emit(
        state,
        {
            "status": "changed" if result.indexed_documents else "unchanged",
            "dry_run": not apply,
            "candidates": result.candidates,
            "indexed_documents": result.indexed_documents,
        },
    )


@maintenance_group.command("backfill-conversation-titles")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 5000),
    default=100,
    show_default=True,
    help="Maximum default-titled conversations processed in this invocation.",
)
@click.option(
    "--apply", is_flag=True, help="Apply changes; otherwise only count candidates."
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def backfill_conversation_titles(
    state: CliState,
    actor_email: str,
    batch_size: int,
    apply: bool,
    yes: bool,
) -> None:
    actor_user = load_user(actor_email)
    if apply:
        confirm("Backfill legacy default conversation titles?", yes=yes)
    invoke = executor().command if apply else executor().query
    result = invoke(
        lambda capabilities: (
            capabilities.conversation_title_maintenance.backfill_default_titles(
                actor=current_admin(capabilities, actor_user.id),
                operation=cli_operation("maintenance.backfill-conversation-titles"),
                batch_size=batch_size,
                apply=apply,
            )
        )
    )
    emit(state, {"dry_run": not apply, **asdict(result)})


def _repair_command(
    command_name: str,
    method_name: str,
    help_text: str,
    *,
    max_batch_size: int = 5000,
    default_batch_size: int = 100,
) -> click.Command:
    @click.command(command_name, cls=OutputGroup.command_class, help=help_text)
    @click.option("--actor-email", required=True, callback=email_callback)
    @click.option(
        "--batch-size",
        type=click.IntRange(1, max_batch_size),
        default=default_batch_size,
        show_default=True,
        help="Maximum rows processed in this invocation and transaction.",
    )
    @click.option(
        "--apply", is_flag=True, help="Apply changes; otherwise only count candidates."
    )
    @click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
    @click.pass_obj
    @guarded
    def _command(
        state: CliState,
        actor_email: str,
        batch_size: int,
        apply: bool,
        yes: bool,
    ) -> None:
        actor_user = load_user(actor_email)
        if apply:
            confirm(f"{help_text}?", yes=yes)
        invoke = executor().command if apply else executor().query
        result = invoke(
            lambda capabilities: getattr(capabilities.data_repair, method_name)(
                actor=current_admin(capabilities, actor_user.id),
                operation=cli_operation(f"maintenance.{command_name}"),
                batch_size=batch_size,
                apply=apply,
            )
        )
        emit(state, {"dry_run": not apply, **asdict(result)})

    return _command


maintenance_group.add_command(
    _repair_command(
        "fix-annotation-offsets",
        "fix_annotation_offsets",
        "Repair annotation anchors whose offsets do not cover the quote",
    )
)


maintenance_group.add_command(
    _repair_command(
        "reprocess-replacement-character-documents",
        "reprocess_unicode_replacement_documents",
        "Enqueue targeted repair for documents containing Unicode replacement characters",
        max_batch_size=50,
        default_batch_size=25,
    )
)


@maintenance_group.command("recover-stuck-paper-ingestion")
@click.option("--actor-email", required=True, callback=email_callback)
@click.option("--job-id", required=True, type=click.UUID)
@click.option(
    "--min-age-seconds",
    type=click.IntRange(60, 7 * 24 * 60 * 60),
    default=3600,
    show_default=True,
)
@click.option("--apply", is_flag=True, help="Apply recovery; otherwise only inspect.")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt when applying.")
@click.pass_obj
@guarded
def recover_stuck_paper_ingestion(
    state: CliState,
    actor_email: str,
    job_id: UUID,
    min_age_seconds: int,
    apply: bool,
    yes: bool,
) -> None:
    """Recover one published PDF ingestion that never acquired a job lease."""
    actor_user = load_user(actor_email)
    if apply:
        confirm(f"Recover stuck paper ingestion {job_id}?", yes=yes)
    invoke = executor().command if apply else executor().query
    result = invoke(
        lambda capabilities: capabilities.data_repair.recover_stuck_paper_ingestion(
            actor=current_admin(capabilities, actor_user.id),
            operation=cli_operation("maintenance.recover-stuck-paper-ingestion"),
            job_id=job_id,
            min_age_seconds=min_age_seconds,
            apply=apply,
        )
    )
    emit(state, {"dry_run": not apply, **asdict(result)})


maintenance_group.add_command(
    _repair_command(
        "reprocess-contaminated-documents",
        "reprocess_contaminated_documents",
        "Enqueue fresh processing for documents with mismatched job results",
    )
)


__all__ = ["maintenance_group"]
