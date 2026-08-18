from uuid import uuid4

import pytest

from app.modules.papers.application.upload_intent import (
    resolve_add_to_library,
    resolve_created_memberships,
)


@pytest.mark.parametrize(
    ("configured", "project_id", "expected"),
    [
        (True, None, True),
        (False, uuid4(), False),
        (None, None, True),
        (None, uuid4(), False),
    ],
)
def test_resolve_add_to_library_preserves_explicit_and_legacy_intent(
    configured: bool | None,
    project_id,
    expected: bool,
) -> None:
    assert resolve_add_to_library(configured, project_id=project_id) is expected


def test_legacy_created_flag_maps_to_the_historical_single_destination() -> None:
    assert resolve_created_memberships(
        library_created=False,
        project_created=False,
        legacy_created=True,
        project_id=None,
    ) == (True, False)
    assert resolve_created_memberships(
        library_created=False,
        project_created=False,
        legacy_created=True,
        project_id=uuid4(),
    ) == (False, True)


def test_split_created_flags_remain_independent() -> None:
    assert resolve_created_memberships(
        library_created=True,
        project_created=True,
        legacy_created=False,
        project_id=uuid4(),
    ) == (True, True)
