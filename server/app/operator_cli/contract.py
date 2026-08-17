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
    from app.transport.http.contract_artifacts import (
        check_contract as check_http_contract,
    )
    from app.transport.http.contract_artifacts import (
        export_contract as export_http_contract,
    )
    from app.transport.mcp.contract_artifacts import (
        check_contract as check_mcp_contract,
    )
    from app.transport.mcp.contract_artifacts import (
        export_contract as export_mcp_contract,
    )

    mismatches = (*check_http_contract(), *check_mcp_contract())
    paths = (*export_http_contract(), *export_mcp_contract()) if mismatches else ()
    changed = bool(mismatches)
    emit(
        state,
        {
            "status": "changed" if changed else "unchanged",
            "files": [str(path) for path in paths],
        },
        human=(
            "Exported the public HTTP and MCP contracts."
            if changed
            else "Public HTTP and MCP contracts are already current."
        ),
    )


@contract_group.command("check")
@click.pass_obj
@guarded
def check_command(state: CliState) -> None:
    from app.transport.http.contract_artifacts import (
        check_contract as check_http_contract,
    )
    from app.transport.mcp.contract_artifacts import (
        check_contract as check_mcp_contract,
    )

    mismatches = (*check_http_contract(), *check_mcp_contract())
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
