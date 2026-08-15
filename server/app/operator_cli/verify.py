"""Deterministic product verification commands."""

from __future__ import annotations

import click

from app.operator_cli.common import CliState, OutputGroup, emit, guarded


@click.group("verify", cls=OutputGroup)
def verify_group() -> None:
    """Run fixture-backed product journeys."""


@verify_group.command("paper-search")
@click.pass_obj
@guarded
def verify_paper_search_command(state: CliState) -> None:
    from app.bootstrap.search_verification import verify_paper_search

    verify_paper_search()
    emit(
        state,
        {"ok": True, "verification": "paper-search"},
        human="Paper search verification passed.",
    )


__all__ = ["verify_group"]
