from __future__ import annotations

import pytest

from scholens_observability import (
    ObservabilityContext,
    bind_context,
    current_context,
    reset_context,
    set_context,
    update_context,
)


def test_bound_context_is_scoped_and_restored() -> None:
    token = set_context(ObservabilityContext(service="test", environment="test"))
    try:
        with bind_context(request_id="request-1", component="chat") as context:
            assert context == current_context()
            assert current_context().request_id == "request-1"
            assert current_context().component == "chat"
        assert current_context().request_id is None
        assert current_context().component is None
    finally:
        reset_context(token)


def test_context_fields_omit_unset_values_and_update_known_fields() -> None:
    token = set_context(ObservabilityContext(service="api", environment="test"))
    try:
        updated = update_context(operation_id="operation-1", stage="persisting")

        assert updated.fields() == {
            "service": "api",
            "environment": "test",
            "operation_id": "operation-1",
            "stage": "persisting",
        }
        with pytest.raises(ValueError, match="Unknown observability context fields"):
            update_context(unknown_field="value")
    finally:
        reset_context(token)
