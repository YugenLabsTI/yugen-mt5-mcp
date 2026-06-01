from __future__ import annotations

import json
from pathlib import Path

from yugen_mt5_mcp.audit import REDACTED, AuditEvent, AuditStore, redact_payload


def test_redact_payload_handles_nested_secret_values() -> None:
    payload = {
        "authorization": "Bearer top-secret",
        "nested": {
            "bearer_token": "abc123",
            "safe": "value",
        },
        "items": [
            {"password": "pw"},
            "Bearer another-secret",
        ],
    }

    redacted = redact_payload(payload)

    assert redacted == {
        "authorization": REDACTED,
        "nested": {
            "bearer_token": REDACTED,
            "safe": "value",
        },
        "items": [
            {"password": REDACTED},
            REDACTED,
        ],
    }


def test_append_persists_redacted_context(tmp_path: Path) -> None:
    database_path = tmp_path / "audit.sqlite3"
    store = AuditStore(database_path)

    event_id = store.append(
        AuditEvent(
            event_type="trade.rejected",
            actor="agent:test",
            request_id="req-123",
            decision="blocked",
            context={
                "reason": "risk policy",
                "api_token": "should-not-leak",
                "headers": {"authorization": "Bearer top-secret"},
            },
        )
    )

    rows = store.fetch_all()

    assert event_id == 1
    assert len(rows) == 1

    payload = json.loads(rows[0]["context_json"])
    assert payload["reason"] == "risk policy"
    assert payload["api_token"] == REDACTED
    assert payload["headers"]["authorization"] == REDACTED
    assert "top-secret" not in rows[0]["context_json"]
