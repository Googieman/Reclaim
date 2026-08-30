"""SQL boundary tests for valid webhook identity and quarantine persistence."""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.base import RepositoryError
from app.db.repositories.webhooks import (
    WebhookDeliveryRepository,
    WebhookIdentityConflictError,
)
from app.db.tenant_context import TenantContext


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
            )
            return Cursor(self.quarantine_row)
        if "SELECT TENANT_ID, CONNECTOR_ID, PROVIDER_EVENT_ID" in normalized:
            return Cursor(self.delivery_row)
        return Cursor(None)


def test_valid_delivery_repository_uses_provider_identity_and_context_tenant() -> None:
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())

    result = repository.create_or_get(
        connector_id="razorpay-test",
        provider_event_id="evt-1",
        original_payload=b"{}",
        payload_checksum="sha256:payload",
        raw_object_uri="tenants/tenant-a/webhooks/evt-1.json",
        signature="signature",
        event_type="payment.captured",
        event_timestamp=NOW,
        received_at=NOW,
    )

    assert result.inserted is True
    assert result.row.provider_event_id == "evt-1"
    assert connection.calls[0][1][0] == "tenant-a"
    assert "action" not in connection.calls[0][0].lower()

    duplicate = repository.create_or_get(
        connector_id="razorpay-test",
        provider_event_id="evt-1",
        original_payload=b"{}",
        payload_checksum="sha256:payload",
        raw_object_uri="tenants/tenant-a/webhooks/evt-1.json",
        signature="signature",
        event_type="payment.captured",
        event_timestamp=NOW,
        received_at=NOW,
    )
    assert duplicate.inserted is False

    with pytest.raises(WebhookIdentityConflictError, match="different raw content"):
        repository.create_or_get(
            connector_id="razorpay-test",
            provider_event_id="evt-1",
            original_payload=b"different",
            payload_checksum="sha256:different",
            raw_object_uri="tenants/tenant-a/webhooks/evt-1.json",
            signature="signature",
            event_type="payment.captured",
            event_timestamp=NOW,
            received_at=NOW,
        )


def test_valid_delivery_rejects_missing_provider_identity_before_sql() -> None:
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())

    with pytest.raises(RepositoryError, match="provider event identity"):
        repository.create_or_get(
            connector_id="razorpay-test",
            provider_event_id=" ",
            original_payload=b"{}",
            payload_checksum="sha256:payload",
            raw_object_uri=None,
            signature=None,
            event_type=None,
            event_timestamp=None,
            received_at=NOW,
        )

    assert connection.calls == []


def test_quarantine_repository_preserves_missing_provider_identity_as_null() -> None:
    connection = Connection()
    repository = WebhookDeliveryRepository(connection, context())

    result = repository.quarantine(
        quarantine_id="quarantine-1",
        connector_id="razorpay-test",
        provider_event_id=None,
        original_payload=b"invalid",
        payload_checksum="sha256:invalid",
        raw_object_uri="tenants/tenant-a/webhooks/quarantine-1.json",
        signature=None,
        event_type=None,
        event_timestamp=None,
        received_at=NOW,
        reason="missing provider event identity",
    )

    assert result.provider_event_id is None
    assert connection.quarantine_row is not None
    assert connection.quarantine_row[3] is None
