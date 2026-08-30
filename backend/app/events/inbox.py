"""Tenant-aware inbox claims and idempotent delivery state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from packages.contracts.events import EventEnvelope

from app.db.repositories.base import RepositoryError, TenantScopedRepository


class InboxConflictError(RepositoryError):
    """Raised when a delivery identity is reused with a different payload checksum."""


class InboxStateError(RepositoryError):
    """Raised when an inbox state transition is not valid for the requested operation."""


class InboxDisposition(StrEnum):
    CLAIMED = "claimed"
    RETRY = "retry"
    ALREADY_HANDLED = "already_handled"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class InboxMessage:
    """Authoritative delivery state for one consumer and one tenant event."""

    tenant_id: str
    consumer_name: str
    event_id: str
    payload_checksum: str
    received_at: datetime
    handled_at: datetime | None
    handling_status: str
    last_error: str | None


@dataclass(frozen=True, slots=True)
class InboxClaim:
    """Result of attempting to claim an event for a consumer."""

    disposition: InboxDisposition
    message: InboxMessage

    @property
    def should_process(self) -> bool:
        return self.disposition in {InboxDisposition.CLAIMED, InboxDisposition.RETRY}


class InboxMessageRepository(TenantScopedRepository):
    """Persist delivery claims; a transport offset is never treated as completion.

    Claim, business-state handling, and ``mark_handled`` are expected to run on the
    same ``PostgresUnitOfWork`` transaction.  A rollback then removes both the claim
    and any business writes, allowing safe redelivery.  A committed handled row makes
    a later at-least-once delivery a no-op for this consumer and tenant.
    """

    def claim(
        self,
        *,
        consumer_name: str,
        event: EventEnvelope,
        received_at: datetime | None = None,
    ) -> InboxClaim:
        self.assert_tenant(event.tenant_id)
        _require_consumer_name(consumer_name)
        inserted_row = self.fetch_one(
            """
            INSERT INTO inbox_messages (
                tenant_id, consumer_name, event_id, payload_checksum, received_at
            )
            VALUES (%s, %s, %s, %s, COALESCE(%s, now()))
            ON CONFLICT (tenant_id, consumer_name, event_id) DO NOTHING
            RETURNING tenant_id, consumer_name, event_id, payload_checksum,
                      received_at, handled_at, handling_status, last_error
            """,
            (
                event.tenant_id,
                consumer_name,
                event.event_id,
                event.payload_checksum,
                received_at,
            ),
        )
        if inserted_row is not None:
            return InboxClaim(
                disposition=InboxDisposition.CLAIMED,
                message=_message_from_row(inserted_row),
            )

        existing_row = self.fetch_one(
            """
            SELECT tenant_id, consumer_name, event_id, payload_checksum,
                   received_at, handled_at, handling_status, last_error
            FROM inbox_messages
            WHERE tenant_id = %s AND consumer_name = %s AND event_id = %s
            FOR UPDATE
            """,
            (self.tenant_context.tenant_id, consumer_name, event.event_id),
        )
        if existing_row is None:
            raise RepositoryError("inbox message disappeared after conflict")

        existing = _message_from_row(existing_row)
        if existing.payload_checksum != event.payload_checksum:
            raise InboxConflictError(
                "inbox delivery identity already exists with a different payload checksum"
            )
        if existing.handling_status == "handled":
            return InboxClaim(InboxDisposition.ALREADY_HANDLED, existing)
        if existing.handling_status == "received":
            return InboxClaim(InboxDisposition.IN_PROGRESS, existing)
        if existing.handling_status == "failed":
            retried_row = self.fetch_one(
                """
                UPDATE inbox_messages
                SET handling_status = 'received', received_at = COALESCE(%s, now()),
                    handled_at = NULL, last_error = NULL
                WHERE tenant_id = %s AND consumer_name = %s AND event_id = %s
                  AND payload_checksum = %s AND handling_status = 'failed'
                RETURNING tenant_id, consumer_name, event_id, payload_checksum,
                          received_at, handled_at, handling_status, last_error
                """,
                (
                    received_at,
                    self.tenant_context.tenant_id,
                    consumer_name,
                    event.event_id,
                    event.payload_checksum,
                ),
            )
            if retried_row is None:
                raise InboxStateError("failed inbox message could not be reclaimed")
            return InboxClaim(
                disposition=InboxDisposition.RETRY,
                message=_message_from_row(retried_row),
            )
        raise InboxStateError(f"unsupported inbox handling status: {existing.handling_status}")

    def mark_handled(
        self,
        *,
        consumer_name: str,
        event_id: str,
        payload_checksum: str,
        handled_at: datetime | None = None,
    ) -> InboxMessage:
        _require_consumer_name(consumer_name)
        row = self.fetch_one(
            """
            UPDATE inbox_messages
            SET handling_status = 'handled', handled_at = COALESCE(%s, now()),
                last_error = NULL
            WHERE tenant_id = %s AND consumer_name = %s AND event_id = %s
              AND payload_checksum = %s AND handling_status = 'received'
            RETURNING tenant_id, consumer_name, event_id, payload_checksum,
                      received_at, handled_at, handling_status, last_error
            """,
            (
                handled_at,
                self.tenant_context.tenant_id,
                consumer_name,
                event_id,
                payload_checksum,
            ),
        )
        if row is not None:
            return _message_from_row(row)
        return self._existing_after_noop(
            consumer_name=consumer_name,
            event_id=event_id,
            payload_checksum=payload_checksum,
            expected_status="handled",
            operation="mark handled",
        )

    def mark_failed(
        self,
        *,
        consumer_name: str,
        event_id: str,
        payload_checksum: str,
        error: str,
    ) -> InboxMessage:
        _require_consumer_name(consumer_name)
        if not error.strip():
            raise InboxStateError("inbox failure requires an error")
        row = self.fetch_one(
            """
            UPDATE inbox_messages
            SET handling_status = 'failed', handled_at = NULL, last_error = %s
            WHERE tenant_id = %s AND consumer_name = %s AND event_id = %s
              AND payload_checksum = %s AND handling_status = 'received'
            RETURNING tenant_id, consumer_name, event_id, payload_checksum,
                      received_at, handled_at, handling_status, last_error
            """,
            (
                error[:2000],
                self.tenant_context.tenant_id,
                consumer_name,
                event_id,
                payload_checksum,
            ),
        )
        if row is not None:
            return _message_from_row(row)
        return self._existing_after_noop(
            consumer_name=consumer_name,
            event_id=event_id,
            payload_checksum=payload_checksum,
            expected_status="failed",
            operation="mark failed",
        )

    def get(self, *, consumer_name: str, event_id: str) -> InboxMessage | None:
        _require_consumer_name(consumer_name)
        row = self.fetch_one(
            """
            SELECT tenant_id, consumer_name, event_id, payload_checksum,
                   received_at, handled_at, handling_status, last_error
            FROM inbox_messages
            WHERE tenant_id = %s AND consumer_name = %s AND event_id = %s
            """,
            (self.tenant_context.tenant_id, consumer_name, event_id),
        )
        return None if row is None else _message_from_row(row)

    def _existing_after_noop(
        self,
        *,
        consumer_name: str,
        event_id: str,
        payload_checksum: str,
        expected_status: str,
        operation: str,
    ) -> InboxMessage:
        existing = self.get(consumer_name=consumer_name, event_id=event_id)
        if existing is None:
            raise RepositoryError(f"cannot {operation}: inbox message does not exist")
        if existing.payload_checksum != payload_checksum:
            raise InboxConflictError(
                "inbox delivery identity already exists with a different payload checksum"
            )
        if existing.handling_status == expected_status:
            return existing
        raise InboxStateError(
            f"cannot {operation} inbox message in {existing.handling_status!r} state"
        )


def _require_consumer_name(consumer_name: str) -> None:
    if not consumer_name.strip():
        raise RepositoryError("consumer_name is required")


def _message_from_row(row: Any) -> InboxMessage:
    return InboxMessage(
        tenant_id=str(row[0]),
        consumer_name=str(row[1]),
        event_id=str(row[2]),
        payload_checksum=str(row[3]),
        received_at=row[4],
        handled_at=row[5],
        handling_status=str(row[6]),
        last_error=None if row[7] is None else str(row[7]),
    )
