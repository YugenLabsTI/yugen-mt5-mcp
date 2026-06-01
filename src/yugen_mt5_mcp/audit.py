"""SQLite-backed append-only audit primitives with secret redaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REDACTED = "***REDACTED***"
_SENSITIVE_KEYWORDS = (
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS)


def redact_payload(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED

    if isinstance(value, Mapping):
        return {
            str(item_key): redact_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }

    if isinstance(value, list | tuple):
        return [redact_payload(item) for item in value]

    if isinstance(value, str) and value.lower().startswith("bearer "):
        return REDACTED

    return value


@dataclass(slots=True, frozen=True)
class AuditEvent:
    event_type: str
    actor: str
    request_id: str
    decision: str
    context: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditStore:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    context_json TEXT NOT NULL
                )
                """
            )

    def append(self, event: AuditEvent) -> int:
        self.initialize()
        redacted_context = redact_payload(event.context)
        payload = json.dumps(redacted_context, sort_keys=True, default=str)

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events (
                    created_at,
                    event_type,
                    actor,
                    request_id,
                    decision,
                    context_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.created_at.isoformat(),
                    event.event_type,
                    event.actor,
                    event.request_id,
                    event.decision,
                    payload,
                ),
            )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("sqlite did not return a row id for audit append")
        return int(row_id)

    def fetch_all(self) -> list[sqlite3.Row]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id ASC"
            ).fetchall()
        return list(rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
