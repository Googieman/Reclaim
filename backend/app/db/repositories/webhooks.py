"""Tenant-scoped provider webhook identity and quarantine repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .base import RepositoryError, TenantScopedRepository


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    tenant_id: str
    connector_id: str
    provider_event_id: str
    original_payload: bytes
    payload_checksum: str
    raw_object_uri: str | None
    signature: str | None
    event_type: str | None
    event_timestamp: datetime | None
    received_at: datetime
    processing_status: str
    incident_id: str | None
    case_id: str | None
    quarantine_reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WebhookDeliveryCreateResult:
    row: WebhookDelivery
    inserted: bool


@dataclass(frozen=True, slots=True)
class WebhookQuarantine:
    tenant_id: str
    quarantine_id: str
    connector_id: str
    provider_event_id: str | None
    original_payload: bytes
    payload_checksum: str
    raw_object_uri: str
    signature: str | None
    event_type: str | None
    event_timestamp: datetime | None
    received_at: datetime
    quarantine_reason: str
    created_at: datetime


class WebhookIdentityConflictError(RepositoryError):
    """Raised when one provider identity is reused with different raw content."""


class WebhookDeliveryRepository(TenantScopedRepository):
    """Persist valid deliveries separately from action idempotency records."""

    def create_or_get(
        self,
        *,
        connector_id: str,
        provider_event_id: str,
        original_payload: bytes,
        payload_checksum: str,
        raw_object_uri: str | None,
        signature: str | None,
        event_type: str | None,
        event_timestamp: datetime | None,
        received_at: datetime,
        incident_id: str | None = None,
        case_id: str | None = None,
    ) -> WebhookDeliveryCreateResult:
        if not provider_event_id.strip():
            raise RepositoryError("valid webhook delivery requires provider event identity")
        row = self.fetch_one(
            """
            INSERT INTO webhook_deliveries (
                tenant_id, connector_id, provider_event_id, original_payload,
                payload_checksum, raw_object_uri, signature, event_type,
                event_timestamp, received_at, processing_status, incident_id, case_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'accepted', %s, %s)
            ON CONFLICT (tenant_id, connector_id, provider_event_id) DO NOTHING
            RETURNING tenant_id, connector_id, provider_event_id, original_payload,
                      payload_checksum, raw_object_uri, signature, event_type,
                      event_timestamp, received_at, processing_status, incident_id,
                      case_id, quarantine_reason, created_at
            """,
            (
                self.tenant_context.tenant_id,
                connector_id,
                provider_event_id,
                original_payload,
                payload_checksum,
                raw_object_uri,
                signature,
                event_type,
                event_timestamp,
                received_at,
                incident_id,
                case_id,
            ),
        )
        if row is not None:
            return WebhookDeliveryCreateResult(_delivery_from_row(row), inserted=True)

        existing_row = self.fetch_one(
            """
            SELECT tenant_id, connector_id, provider_event_id, original_payload,
                   payload_checksum, raw_object_uri, signature, event_type,
                   event_timestamp, received_at, processing_status, incident_id,
                   case_id, quarantine_reason, created_at
            FROM webhook_deliveries
            WHERE tenant_id = %s AND connector_id = %s AND provider_event_id = %s
            """,
            (self.tenant_context.tenant_id, connector_id, provider_event_id),
        )
        if existing_row is None:
            raise RepositoryError("webhook delivery disappeared after identity conflict")
        existing = _delivery_from_row(existing_row)
        if (
            existing.payload_checksum != payload_checksum
            or existing.original_payload != original_payload
        ):
            raise WebhookIdentityConflictError(
                "provider webhook identity already exists with different raw content"
            )
        return WebhookDeliveryCreateResult(existing, inserted=False)

    def get(self, *, connector_id: str, provider_event_id: str) -> WebhookDelivery | None:
        row = self.fetch_one(
            """
            SELECT tenant_id, connector_id, provider_event_id, original_payload,
                   payload_checksum, raw_object_uri, signature, event_type,
                   event_timestamp, received_at, processing_status, incident_id,
                   case_id, quarantine_reason, created_at
            FROM webhook_deliveries
            WHERE tenant_id = %s AND connector_id = %s AND provider_event_id = %s
            """,
            (self.tenant_context.tenant_id, connector_id, provider_event_id),
        )
        return None if row is None else _delivery_from_row(row)

    def quarantine(
        self,
        *,
        quarantine_id: str,
        connector_id: str,
        provider_event_id: str | None,
        original_payload: bytes,
        payload_checksum: str,
        raw_object_uri: str,
        signature: str | None,
        event_type: str | None,
        event_timestamp: datetime | None,
        received_at: datetime,
        reason: str,
    ) -> WebhookQuarantine:
        if not quarantine_id.strip() or not reason.strip():
            raise RepositoryError("quarantine identity and reason are required")
        row = self.fetch_one(
            """
            INSERT INTO webhook_quarantines (
                tenant_id, quarantine_id, connector_id, provider_event_id,
                original_payload, payload_checksum, raw_object_uri, signature,
                event_type, event_timestamp, received_at, quarantine_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, quarantine_id, connector_id, provider_event_id,
                      original_payload, payload_checksum, raw_object_uri, signature,
                      event_type, event_timestamp, received_at, quarantine_reason,
                      created_at
            """,
            (
                self.tenant_context.tenant_id,
                quarantine_id,
                connector_id,
                provider_event_id,
                original_payload,
                payload_checksum,
                raw_object_uri,
                signature,
                event_type,
                event_timestamp,
                received_at,
                reason,
            ),
        )
        if row is None:
            raise RuntimeError("webhook quarantine insert returned no row")
        return _quarantine_from_row(row)


def _delivery_from_row(row: Any) -> WebhookDelivery:
    return WebhookDelivery(
        tenant_id=str(row[0]),
        connector_id=str(row[1]),
        provider_event_id=str(row[2]),
        original_payload=bytes(row[3]),
        payload_checksum=str(row[4]),
        raw_object_uri=None if row[5] is None else str(row[5]),
        signature=None if row[6] is None else str(row[6]),
        event_type=None if row[7] is None else str(row[7]),
        event_timestamp=row[8],
        received_at=row[9],
        processing_status=str(row[10]),
        incident_id=None if row[11] is None else str(row[11]),
        case_id=None if row[12] is None else str(row[12]),
        quarantine_reason=None if row[13] is None else str(row[13]),
        created_at=row[14],
    )


def _quarantine_from_row(row: Any) -> WebhookQuarantine:
    return WebhookQuarantine(
        tenant_id=str(row[0]),
        quarantine_id=str(row[1]),
        connector_id=str(row[2]),
        provider_event_id=None if row[3] is None else str(row[3]),
        original_payload=bytes(row[4]),
        payload_checksum=str(row[5]),
        raw_object_uri=str(row[6]),
        signature=None if row[7] is None else str(row[7]),
        event_type=None if row[8] is None else str(row[8]),
        event_timestamp=row[9],
        received_at=row[10],
        quarantine_reason=str(row[11]),
        created_at=row[12],
    )
