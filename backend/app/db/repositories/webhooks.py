"""Tenant-scoped provider webhook deliveries and quarantine records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from packages.contracts.intake import VerifiedProviderCorrelation

from .base import RepositoryError, TenantScopedRepository
from .provider_correlations import (
    ProviderCorrelationMapping,
    correlation_from_json,
    correlation_to_json,
)


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
    authoritative_mapping_id: str | None = None
    related_order_reference: str | None = None
    related_payment_reference: str | None = None
    verified_provider_correlation: VerifiedProviderCorrelation | None = None
    asserted_tenant_id: str | None = None
    asserted_merchant_id: str | None = None
    asserted_incident_id: str | None = None
    asserted_case_id: str | None = None
    assertion_status: str | None = None


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
    verified_provider_correlation: VerifiedProviderCorrelation | None = None
    association_status: str | None = None
    asserted_tenant_id: str | None = None
    asserted_merchant_id: str | None = None
    asserted_incident_id: str | None = None
    asserted_case_id: str | None = None


class WebhookIdentityConflictError(RepositoryError):
    """Raised when one provider identity is reused with different raw content."""


class WebhookCorrelationConflictError(RepositoryError):
    """Raised when an idempotent provider identity carries different correlation."""


class WebhookDeliveryRepository(TenantScopedRepository):
    """Persist only deliveries resolved through an authoritative provider mapping."""

    _SELECT_COLUMNS = """
        tenant_id, connector_id, provider_event_id, original_payload, payload_checksum,
        raw_object_uri, signature, event_type, event_timestamp, received_at,
        processing_status, authoritative_mapping_id, incident_id, case_id,
        related_order_reference, related_payment_reference, verified_correlation,
        asserted_tenant_id, asserted_merchant_id, asserted_incident_id,
        asserted_case_id, assertion_status, quarantine_reason, created_at
    """

    def create_or_get(
        self,
        *,
        mapping: ProviderCorrelationMapping,
        verified_provider_correlation: VerifiedProviderCorrelation,
        connector_id: str,
        provider_event_id: str,
        original_payload: bytes,
        payload_checksum: str,
        raw_object_uri: str | None,
        signature: str | None,
        event_type: str | None,
        event_timestamp: datetime | None,
        received_at: datetime,
        asserted_tenant_id: str,
        asserted_merchant_id: str | None = None,
        asserted_incident_id: str | None = None,
        asserted_case_id: str | None = None,
        assertion_status: str = "matched",
    ) -> WebhookDeliveryCreateResult:
        if not provider_event_id.strip():
            raise RepositoryError("valid webhook delivery requires provider event identity")
        _validate_delivery_mapping(
            mapping=mapping,
            correlation=verified_provider_correlation,
            connector_id=connector_id,
            provider_event_id=provider_event_id,
            payload_checksum=payload_checksum,
            tenant_id=self.tenant_context.tenant_id,
            asserted_tenant_id=asserted_tenant_id,
            asserted_incident_id=asserted_incident_id,
            asserted_case_id=asserted_case_id,
            assertion_status=assertion_status,
        )
        row = self.fetch_one(
            f"""
            INSERT INTO webhook_deliveries (
                tenant_id, connector_id, provider_event_id, original_payload,
                payload_checksum, raw_object_uri, signature, event_type,
                event_timestamp, received_at, processing_status,
                authoritative_mapping_id, incident_id, case_id,
                related_order_reference, related_payment_reference,
                verified_correlation, asserted_tenant_id, asserted_merchant_id,
                asserted_incident_id, asserted_case_id, assertion_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'accepted',
                    %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, connector_id, provider_event_id) DO NOTHING
            RETURNING {self._SELECT_COLUMNS}
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
                mapping.mapping_id,
                mapping.incident_id,
                mapping.case_id,
                mapping.related_order_reference,
                mapping.related_payment_reference,
                correlation_to_json(verified_provider_correlation),
                asserted_tenant_id,
                asserted_merchant_id,
                asserted_incident_id,
                asserted_case_id,
                assertion_status,
            ),
        )
        if row is not None:
            return WebhookDeliveryCreateResult(_delivery_from_row(row), inserted=True)

        existing_row = self.fetch_one(
            f"""
            SELECT {self._SELECT_COLUMNS}
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
        if existing.verified_provider_correlation != verified_provider_correlation:
            raise WebhookCorrelationConflictError(
                "provider webhook identity already exists with different correlation"
            )
        return WebhookDeliveryCreateResult(existing, inserted=False)

    def get(self, *, connector_id: str, provider_event_id: str) -> WebhookDelivery | None:
        row = self.fetch_one(
            f"""
            SELECT {self._SELECT_COLUMNS}
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
        verified_provider_correlation: VerifiedProviderCorrelation | None = None,
        association_status: str | None = None,
        asserted_tenant_id: str | None = None,
        asserted_merchant_id: str | None = None,
        asserted_incident_id: str | None = None,
        asserted_case_id: str | None = None,
    ) -> WebhookQuarantine:
        if not quarantine_id.strip() or not reason.strip():
            raise RepositoryError("quarantine identity and reason are required")
        row = self.fetch_one(
            """
            INSERT INTO webhook_quarantines (
                tenant_id, quarantine_id, connector_id, provider_event_id,
                original_payload, payload_checksum, raw_object_uri, signature,
                event_type, event_timestamp, received_at, quarantine_reason,
                verified_correlation, association_status, asserted_tenant_id,
                asserted_merchant_id, asserted_incident_id, asserted_case_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING tenant_id, quarantine_id, connector_id, provider_event_id,
                      original_payload, payload_checksum, raw_object_uri, signature,
                      event_type, event_timestamp, received_at, quarantine_reason,
                      created_at, verified_correlation, association_status,
                      asserted_tenant_id, asserted_merchant_id, asserted_incident_id,
                      asserted_case_id
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
                correlation_to_json(verified_provider_correlation),
                association_status,
                asserted_tenant_id,
                asserted_merchant_id,
                asserted_incident_id,
                asserted_case_id,
            ),
        )
        if row is None:
            raise RuntimeError("webhook quarantine insert returned no row")
        return _quarantine_from_row(row)


def _validate_delivery_mapping(
    *,
    mapping: ProviderCorrelationMapping,
    correlation: VerifiedProviderCorrelation,
    connector_id: str,
    provider_event_id: str,
    payload_checksum: str,
    tenant_id: str,
    asserted_tenant_id: str,
    asserted_incident_id: str | None,
    asserted_case_id: str | None,
    assertion_status: str,
) -> None:
    if mapping.tenant_id != tenant_id:
        raise RepositoryError("provider mapping crosses transaction tenant boundary")
    if mapping.mapping_status != "active":
        raise RepositoryError("provider mapping is not active")
    if mapping.correlation_schema_version != correlation.correlation_schema_version:
        raise RepositoryError("provider mapping schema does not match correlation")
    if mapping.connector_id != connector_id or mapping.provider != correlation.provider:
        raise RepositoryError("provider mapping does not match configured connector")
    if (
        correlation.connector_id != connector_id
        or correlation.provider_event_id != provider_event_id
    ):
        raise RepositoryError("verified provider correlation does not match delivery")
    if correlation.verification.payload_checksum != payload_checksum:
        raise RepositoryError("verified provider correlation checksum does not match delivery")
    for field_name in (
        "provider_event_id",
        "provider_payment_id",
        "provider_order_id",
        "merchant_reference",
    ):
        mapping_value = getattr(mapping, field_name)
        correlation_value = getattr(correlation, field_name)
        if (
            mapping_value is not None
            and correlation_value is not None
            and mapping_value != correlation_value
        ):
            raise RepositoryError(f"provider mapping {field_name} does not match correlation")
    if asserted_tenant_id != tenant_id:
        raise RepositoryError("caller tenant assertion does not match transaction tenant")
    if asserted_incident_id is not None and asserted_incident_id != mapping.incident_id:
        raise RepositoryError("caller incident assertion does not match provider mapping")
    if asserted_case_id is not None and asserted_case_id != mapping.case_id:
        raise RepositoryError("caller case assertion does not match provider mapping")
    if assertion_status not in {"not_supplied", "matched"}:
        raise RepositoryError("invalid provider mapping assertion status")


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
        authoritative_mapping_id=None if row[11] is None else str(row[11]),
        incident_id=None if row[12] is None else str(row[12]),
        case_id=None if row[13] is None else str(row[13]),
        related_order_reference=None if row[14] is None else str(row[14]),
        related_payment_reference=None if row[15] is None else str(row[15]),
        verified_provider_correlation=correlation_from_json(row[16]),
        asserted_tenant_id=None if row[17] is None else str(row[17]),
        asserted_merchant_id=None if row[18] is None else str(row[18]),
        asserted_incident_id=None if row[19] is None else str(row[19]),
        asserted_case_id=None if row[20] is None else str(row[20]),
        assertion_status=None if row[21] is None else str(row[21]),
        quarantine_reason=None if row[22] is None else str(row[22]),
        created_at=row[23],
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
        verified_provider_correlation=correlation_from_json(row[13]),
        association_status=None if row[14] is None else str(row[14]),
        asserted_tenant_id=None if row[15] is None else str(row[15]),
        asserted_merchant_id=None if row[16] is None else str(row[16]),
        asserted_incident_id=None if row[17] is None else str(row[17]),
        asserted_case_id=None if row[18] is None else str(row[18]),
    )
