"""Guarded product maintenance commands."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

import click

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
