"""Public contract artifact commands."""

from __future__ import annotations

import click

from app.operator_cli.common import CliState, OutputGroup, emit, guarded


@click.group("contract", cls=OutputGroup)
def contract_group() -> None:
    """Export or check committed public API artifacts."""


@contract_group.command("export")
@click.pass_obj
@guarded
def export_command(state: CliState) -> None:
    from app.transport.http.contract_artifacts import check_contract, export_contract

    mismatches = check_contract()
    paths = export_contract() if mismatches else ()
    changed = bool(mismatches)
    emit(
        state,
        {
            "status": "changed" if changed else "unchanged",
            "files": [str(path) for path in paths],
        },
        human=(
            "Exported the public OpenAPI contract."
            if changed
            else "Public OpenAPI contract is already current."
        ),
    )


@contract_group.command("check")
@click.pass_obj
@guarded
def check_command(state: CliState) -> None:
    from app.transport.http.contract_artifacts import check_contract

    mismatches = check_contract()
    payload = {"ok": not mismatches, "mismatches": [str(path) for path in mismatches]}
    emit(
        state,
        payload,
        human="Public contract is current."
        if not mismatches
        else "Public contract is stale.",
    )
    if mismatches:
        raise click.exceptions.Exit(1)


__all__ = ["contract_group"]
