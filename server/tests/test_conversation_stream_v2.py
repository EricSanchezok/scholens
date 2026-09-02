from __future__ import annotations

import json
from uuid import UUID

from app.transport.http.public_v2.turns import _stable_seq, _upgrade_frame


RESPONSE_ID = UUID("60000000-0000-4000-8000-000000000001")


def _payload(frame: str) -> dict[str, object]:
    raw = next(
        line.removeprefix("data: ")
        for line in frame.splitlines()
        if line.startswith("data: ")
    )
    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def test_redis_cursor_becomes_a_monotonic_v2_sequence() -> None:
    assert _stable_seq("1710000000000-1", 1) < _stable_seq("1710000000001-0", 1)
    assert _stable_seq(None, 7) == 7


def test_v2_upgrade_preserves_safe_phase_and_resume_id() -> None:
    frame = _upgrade_frame(
        'id: 1710000000000-1\nevent: phase\ndata: {"type":"phase","response_id":"60000000-0000-4000-8000-000000000001","phase":"tool","elapsed_ms":1200}\n\n',
        response_id=RESPONSE_ID,
        fallback_seq=1,
    )
    assert frame.startswith("id: 1710000000000-1\nevent: phase.updated")
    payload = _payload(frame)
    assert payload["protocol_version"] == 2
    assert payload["event"] == "phase.updated"
    assert payload["seq"] > 0
    assert payload["data"] == {"phase": "tool", "elapsed_ms": 1200}


def test_v2_upgrade_does_not_expose_tool_arguments() -> None:
    frame = _upgrade_frame(
        'event: activity\ndata: {"type":"activity","response_id":"60000000-0000-4000-8000-000000000001","activity":{"kind":"activity","id":"a-1","sequence":1,"category":"search","state":"running","subject":"papers","connector_name":"scholight","raw_args":{"secret":"x"}}}\n\n',
        response_id=RESPONSE_ID,
        fallback_seq=2,
    )
    payload = _payload(frame)
    data = payload["data"]
    assert isinstance(data, dict)
    presentation = data["presentation"]
    assert isinstance(presentation, dict)
    assert "raw_args" not in presentation
    assert presentation["category"] == "search"
