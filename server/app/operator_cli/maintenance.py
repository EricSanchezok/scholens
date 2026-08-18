"""Guarded product maintenance commands."""

from __future__ import annotations

from dataclasses import asdict

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


def _batch_options() -> list[click.Option]:
    return [
        click.Option(
            ["--batch-size"],
            type=click.IntRange(1, 5000),
            default=100,
            show_default=True,
            help="Maximum rows processed in this invocation and transaction.",
        ),
        click.Option(
            ["--apply"],
            is_flag=True,
            help="Apply changes; otherwise only count candidates.",
        ),
        click.Option(
            ["--yes"],
            is_flag=True,
            help="Skip confirmation prompt when applying.",
        ),
    ]


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


def _repair_command(name: str, help_text: str) -> click.Command:
    @click.command(name, cls=OutputGroup.command_class, help=help_text)
    @click.option("--actor-email", required=True, callback=email_callback)
    @click.option(
        "--batch-size",
        type=click.IntRange(1, 5000),
        default=100,
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
            lambda capabilities: getattr(capabilities.data_repair, name)(
                actor=current_admin(capabilities, actor_user.id),
                operation=cli_operation(f"maintenance.{name}"),
                batch_size=batch_size,
                apply=apply,
            )
        )
        emit(state, {"dry_run": not apply, **asdict(result)})

    return _command


maintenance_group.add_command(
    _repair_command(
        "fix_publish_dates",
        "Normalize date-only publish_date values into timestamps",
    )
)
maintenance_group.add_command(
    _repair_command(
        "fix_annotation_offsets",
        "Repair annotation anchors whose offsets do not cover the quote",
    )
)
maintenance_group.add_command(
    _repair_command(
        "purge_bad_citations",
        "Clear provider-derived citation fields that do not match the paper",
    )
)
maintenance_group.add_command(
    _repair_command(
        "reprocess_contaminated_documents",
        "Enqueue fresh processing for documents with mismatched job results",
    )
)


__all__ = ["maintenance_group"]
