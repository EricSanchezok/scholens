"""Compatibility rules for the rolling migration of upload destinations."""

from __future__ import annotations

from uuid import UUID


def resolve_add_to_library(
    configured: bool | None,
    *,
    project_id: UUID | None,
) -> bool:
    """Resolve new intent while preserving rows written by the old application.

    Before ``add_to_library`` existed, personal uploads created a Library
    membership and Project uploads created only a Project membership. The
    additive migration deliberately leaves old-version writes as ``NULL`` so
    mixed application versions remain distinguishable during rollout.
    """

    if configured is not None:
        return configured
    return project_id is None


def resolve_created_memberships(
    *,
    library_created: bool,
    project_created: bool,
    legacy_created: bool,
    project_id: UUID | None,
) -> tuple[bool, bool]:
    """Merge split flags with the pre-migration single-side cleanup flag."""

    return (
        library_created or (legacy_created and project_id is None),
        project_created or (legacy_created and project_id is not None),
    )
