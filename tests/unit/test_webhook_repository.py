"""SQL boundary tests for D3 mapping-backed webhook persistence."""

from datetime import UTC, datetime
import json
from typing import Any

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.base import RepositoryError
from app.db.repositories.provider_correlations import ProviderCorrelationMapping
from app.db.repositories.webhooks import WebhookDeliveryRepository
from app.db.tenant_context import TenantContext
from packages.contracts.intake import (
    VerifiedProviderCorrelation,
    VerifiedProviderVerification,
)

NOW = datetime(2026, 8, 30, 9, tzinfo=UTC)


def context() -> Any:
    principal = AuthenticatedPrincipal(
        subject="intake-service",
        tenant_ids=frozenset({"tenant-a"}),
        tenant_roles={"tenant-a": frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return TenantContext.from_authorization_context(principal.for_tenant("tenant-a"))


def mapping() -> ProviderCorrelationMapping:
    return ProviderCorrelationMapping(
        tenant_id="tenant-a",
        mapping_id="mapping-1",
        correlation_schema_version="1.0.0",
        provider="razorpay",
        connector_id="razorpay-test",
        provider_event_id=None,
        provider_payment_id="pay-1",
        provider_order_id="order-1",
        merchant_reference="merchant-ref-1",
        incident_id="incident-1",
        case_id="case-1",
        related_order_reference="merchant://orders/order-1",
        related_payment_reference="merchant://payments/pay-1",
        mapping_source="merchant_order_payment_context",
        mapping_source_reference="merchant://orders/order-1",
        mapping_source_checksum="sha256:trusted-mapping",
        mapping_status="active",
        created_at=NOW,
        verified_at=NOW,
        revoked_at=None,
    )


def correlation() -> VerifiedProviderCorrelation:
    return VerifiedProviderCorrelation(
        provider="razorpay",
        connector_id="razorpay-test",
        provider_event_id="evt-1",
        provider_payment_id="pay-1",
        provider_order_id="order-1",
        merchant_reference="merchant-ref-1",
        verification=VerifiedProviderVerification(
            state="verified",
            method="hmac-sha256-original-payload",
            provenance="secret/data/tenants/tenant-a/connectors/razorpay-test/webhook",
            payload_checksum="sha256:payload",
            verifier_version="razorpay-webhook-verifier@2.0.0",
            verified_at=NOW,
        ),
    )


class Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.delivery_row: tuple[object, ...] | None = None
        self.quarantine_row: tuple[object, ...] | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Cursor:
        self.calls.append((query, params))
        normalized = " ".join(query.split()).upper()
        if "INSERT INTO WEBHOOK_DELIVERIES" in normalized:
            if self.delivery_row is not None:
                return Cursor(None)
            self.delivery_row = (
                params[0],
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
                params[6],
                params[7],
                params[8],
                params[9],
                "accepted",
                params[10],
                params[11],
                params[12],
                params[13],
                params[14],
                json.loads(str(params[15])),
                params[16],
                params[17],
                params[18],
                params[19],
                params[20],
                None,
                NOW,
            )
            return Cursor(self.delivery_row)
        if "INSERT INTO WEBHOOK_QUARANTINES" in normalized:
            self.quarantine_row = (
                params[0],
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
                params[6],
                params[7],
                params[8],
                params[9],
                params[10],
                params[11],
                NOW,
                json.loads(str(params[12])),
                params[13],
                params[14],
                params[15],
                params[16],
                params[17],
            )
            return Cursor(self.quarantine_row)
        if "SELECT TENANT_ID, CONNECTOR_ID, PROVIDER_EVENT_ID" in normalized:
            return Cursor(self.delivery_row)
        return Cursor(None)


def delivery_kwargs() -> dict[str, object]:
    return {
        "mapping": mapping(),
        "verified_provider_correlation": correlation(),
        "connector_id": "razorpay-test",
        "provider_event_id": "evt-1",
        "original_payload": b"payload",
        "payload_checksum": "sha256:payload",
        "raw_object_uri": "tenants/tenant-a/webhooks/evt-1.json",
        "signature": "signature",
        "event_type": "payment.captured",
        "event_timestamp": NOW,
        "received_at": NOW,
        "asserted_tenant_id": "tenant-a",
        "asserted_incident_id": None,
        "asserted_case_id": None,
    }


def test_delivery_repository_persists_verified_mapping_and_context_tenant() -> None:
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())

    result = repository.create_or_get(**delivery_kwargs())

    assert result.inserted is True
    assert result.row.provider_event_id == "evt-1"
    assert result.row.authoritative_mapping_id == "mapping-1"
    assert result.row.case_id == "case-1"
    assert result.row.verified_provider_correlation == correlation()
    assert connection.calls[0][1][0] == "tenant-a"
    assert "action" not in connection.calls[0][0].lower()


def test_delivery_repository_rejects_missing_provider_identity_before_sql() -> None:
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())
    values = delivery_kwargs()
    values["provider_event_id"] = " "

    with pytest.raises(RepositoryError, match="provider event identity"):
        repository.create_or_get(**values)

    assert connection.calls == []


def test_quarantine_repository_preserves_verified_correlation_without_authority() -> (
    None
):
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())

    result = repository.quarantine(
        quarantine_id="quarantine-1",
        connector_id="razorpay-test",
        provider_event_id="evt-1",
        original_payload=b"invalid",
        payload_checksum="sha256:invalid",
        raw_object_uri="tenants/tenant-a/webhooks/quarantine-1.json",
        signature="signature",
        event_type="payment.captured",
        event_timestamp=NOW,
        received_at=NOW,
        reason="unresolved_association",
        verified_provider_correlation=correlation(),
        association_status="unresolved_association",
        asserted_tenant_id="tenant-a",
        asserted_case_id="case-arbitrary",
    )

    assert result.provider_event_id == "evt-1"
    assert result.verified_provider_correlation == correlation()
    assert result.association_status == "unresolved_association"
    assert result.asserted_case_id == "case-arbitrary"
    assert connection.quarantine_row is not None
