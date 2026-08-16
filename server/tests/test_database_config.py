from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.database.config import Settings


def test_pool_settings_accept_zero_overflow_and_supported_boundaries() -> None:
    minimum = Settings(
        _env_file=None,
        DATABASE_POOL_SIZE=1,
        DATABASE_MAX_OVERFLOW=0,
    )
    maximum = Settings(
        _env_file=None,
        DATABASE_POOL_SIZE=20,
        DATABASE_MAX_OVERFLOW=20,
    )

    assert (minimum.DATABASE_POOL_SIZE, minimum.DATABASE_MAX_OVERFLOW) == (1, 0)
    assert (maximum.DATABASE_POOL_SIZE, maximum.DATABASE_MAX_OVERFLOW) == (20, 20)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_POOL_SIZE", 0),
        ("DATABASE_POOL_SIZE", 21),
        ("DATABASE_POOL_SIZE", "not-a-number"),
        ("DATABASE_MAX_OVERFLOW", -1),
        ("DATABASE_MAX_OVERFLOW", 21),
    ],
)
def test_pool_settings_reject_values_outside_the_safe_range(
    name: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})
