"""Transaction-aware PostgreSQL protocol double for persistence contract tests.

These tests exercise repository SQL, transaction sharing, and state transitions
without presenting an in-memory result as live PostgreSQL validation.  A real
PostgreSQL run remains a separate environment prerequisite.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from packages.contracts.events import EventEnvelope, EventType


FIXED_NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class RecordingDatabase:
    """A minimal committed-state store with per-connection transaction staging."""

    def __init__(self) -> None:
        self.business_rows = 0
        self.outbox: dict[tuple[str, str], tuple[Any, ...]] = {}
        self.inbox: dict[tuple[str, str, str], tuple[Any, ...]] = {}

    def connect(self) -> RecordingConnection:
        return RecordingConnection(self)


class RecordingConnection:
    def __init__(self, database: RecordingDatabase) -> None:
        self.database = database
        self.calls: list[tuple[str, object]] = []
        self._business_rows = 0
        self._outbox: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._inbox: dict[tuple[str, str, str], tuple[Any, ...]] = {}
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, query: str, params: object = ()) -> Cursor:
        normalized = " ".join(query.split()).upper()
        self.calls.append((query, params))
        values = tuple(params) if isinstance(params, (tuple, list)) else ()

        if normalized == "BEGIN":
            return Cursor([])
        if "SET_CONFIG('RECLAIM.TENANT_ID'" in normalized:
            return Cursor([])
        if "INSERT INTO INCIDENTS" in normalized:
            self._business_rows += 1
            return Cursor(
                [
                    (
                        values[0],
                        values[1],
                        values[2],
                        FIXED_NOW,
                        values[4],
                        values[6],
                        values[7],
                        values[8],
                    )
                ]
            )
        if "INSERT INTO OUTBOX_EVENTS" in normalized:
            key = (str(values[0]), str(values[2]))
            if key in self._outbox or key in self.database.outbox:
                return Cursor([])
            row = (
                values[0],
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
                values[8],
                values[9],
                values[10],
                values[11],
                json.loads(str(values[12])),
                None,
                FIXED_NOW,
            )
            self._outbox[key] = row
            return Cursor([row])
        if "SELECT TENANT_ID, OUTBOX_ID" in normalized:
            key = (str(values[0]), str(values[1]))
            row = self._outbox.get(key) or self.database.outbox.get(key)
            return Cursor([] if row is None else [row])
        if "INSERT INTO INBOX_MESSAGES" in normalized:
            key = (str(values[0]), str(values[1]), str(values[2]))
            if key in self._inbox or key in self.database.inbox:
                return Cursor([])
            row = (
                values[0],
                values[1],
                values[2],
                values[3],
                values[4] or FIXED_NOW,
                None,
                "received",
                None,
            )
            self._inbox[key] = row
            return Cursor([row])
        if "SELECT TENANT_ID, CONSUMER_NAME, EVENT_ID" in normalized:
            key = (str(values[0]), str(values[1]), str(values[2]))
            row = self._inbox.get(key) or self.database.inbox.get(key)
            return Cursor([] if row is None else [row])
        if "SET HANDLING_STATUS = 'RECEIVED'" in normalized:
            key = (str(values[1]), str(values[2]), str(values[3]))
            row = self._inbox.get(key) or self.database.inbox.get(key)
            if row is None or row[3] != values[4] or row[6] != "failed":
                return Cursor([])
            updated = (
                row[0], row[1], row[2], row[3], values[0] or FIXED_NOW, None, "received", None
            )
            self._inbox[key] = updated
            return Cursor([updated])
        if "SET HANDLING_STATUS = 'HANDLED'" in normalized:
            key = (str(values[1]), str(values[2]), str(values[3]))
            row = self._inbox.get(key) or self.database.inbox.get(key)
            if row is None or row[3] != values[4] or row[6] != "received":
                return Cursor([])
            updated = (
                row[0], row[1], row[2], row[3], row[4], values[0] or FIXED_NOW, "handled", None
            )
            self._inbox[key] = updated
            return Cursor([updated])
        if "SET HANDLING_STATUS = 'FAILED'" in normalized:
            key = (str(values[1]), str(values[2]), str(values[3]))
            row = self._inbox.get(key) or self.database.inbox.get(key)
            if row is None or row[3] != values[4] or row[6] != "received":
                return Cursor([])
            updated = (row[0], row[1], row[2], row[3], row[4], None, "failed", values[0])
            self._inbox[key] = updated
            return Cursor([updated])
        return Cursor([])

    def commit(self) -> None:
        self.database.business_rows += self._business_rows
        self.database.outbox.update(self._outbox)
        self.database.inbox.update(self._inbox)
        self.committed = True

    def rollback(self) -> None:
        self._business_rows = 0
        self._outbox.clear()
        self._inbox.clear()
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def make_event(
    *,
    tenant_id: str = "tenant-a",
    event_id: str = "event-1",
    payload_checksum: str = "sha256:payload-1",
    payload: dict[str, object] | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        tenant_id=tenant_id,
        correlation_id="corr-1",
        event_id=event_id,
        event_type=EventType.INCIDENT_ACCEPTED,
        aggregate_type="incident",
        aggregate_id="incident-1",
        occurred_at=FIXED_NOW,
        produced_at=FIXED_NOW,
        causation_id="command-1",
        producer="intake-api@1.0.0",
        payload_checksum=payload_checksum,
        payload=payload or {"source": "operator"},
    )
