"""Unit coverage for provider-mapping idempotency and fail-closed resolution."""

from datetime import UTC, datetime
import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.provider_correlations import (
    ProviderCorrelationMapping,
    ProviderCorrelationMappingConflictError,
    ProviderCorrelationRepository,
)
from app.db.repositories.base import RepositoryError
from app.db.tenant_context import TenantContext
from packages.contracts.intake import VerifiedProviderCorrelation

NOW = datetime(2026, 8, 30, 9, tzinfo=UTC)


def context() -> TenantContext:
    principal = AuthenticatedPrincipal(
        subject="mapping-service",
        tenant_ids=frozenset({"tenant-a"}),
        tenant_roles={"tenant-a": frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return TenantContext.from_authorization_context(principal.for_tenant("tenant-a"))


def user_context() -> TenantContext:
    principal = AuthenticatedPrincipal(
        subject="mapping-reviewer",
        tenant_ids=frozenset({"tenant-a"}),
        tenant_roles={"tenant-a": frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return TenantContext.from_authorization_context(principal.for_tenant("tenant-a"))


def mapping(**overrides: object) -> ProviderCorrelationMapping:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "mapping_id": "mapping-1",
        "correlation_schema_version": "1.0.0",
        "provider": "razorpay",
        "connector_id": "razorpay-test",
        "provider_event_id": None,
        "provider_payment_id": "pay-1",
        "provider_order_id": "order-1",
        "merchant_reference": "merchant-ref-1",
        "incident_id": "incident-1",
        "case_id": "case-1",
        "related_order_reference": "merchant://orders/order-1",
        "related_payment_reference": "merchant://payments/pay-1",
        "mapping_source": "merchant_order_payment_context",
        "mapping_source_reference": "merchant://orders/order-1",
        "mapping_source_checksum": "sha256:trusted-mapping",
        "mapping_status": "active",
        "created_at": NOW,
        "verified_at": NOW,
        "revoked_at": None,
    }
    values.update(overrides)
    return ProviderCorrelationMapping(**values)


def correlation(**overrides: object) -> VerifiedProviderCorrelation:
    values: dict[str, object] = {
        "provider": "razorpay",
        "connector_id": "razorpay-test",
        "provider_event_id": "evt-1",
        "provider_payment_id": "pay-1",
        "provider_order_id": "order-1",
        "merchant_reference": "merchant-ref-1",
        "verification": {
            "state": "verified",
            "method": "hmac-sha256-original-payload",
            "provenance": "secret/data/tenants/tenant-a/connectors/razorpay-test/webhook",
            "payload_checksum": "sha256:payload",
            "verifier_version": "razorpay-webhook-verifier@2.0.0",
            "verified_at": NOW,
        },
    }
    values.update(overrides)
    return VerifiedProviderCorrelation(**values)


def row(value: ProviderCorrelationMapping) -> tuple[object, ...]:
    return (
        value.tenant_id,
        value.mapping_id,
        value.correlation_schema_version,
        value.provider,
        value.connector_id,
        value.provider_event_id,
        value.provider_payment_id,
        value.provider_order_id,
        value.merchant_reference,
        value.incident_id,
        value.case_id,
        value.related_order_reference,
        value.related_payment_reference,
        value.mapping_source,
        value.mapping_source_reference,
        value.mapping_source_checksum,
        value.mapping_status,
        value.created_at,
        value.verified_at,
        value.revoked_at,
    )


class Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class Connection:
    def __init__(
        self,
        *resolution_rows: ProviderCorrelationMapping,
        existing_mapping: ProviderCorrelationMapping | None = None,
    ) -> None:
        self.mapping_row: tuple[object, ...] | None = None
        self.existing_mapping = existing_mapping
        self.resolution_rows = [row(value) for value in resolution_rows]
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Cursor:
        self.calls.append((query, params))
        normalized = " ".join(query.split()).upper()
        if "INSERT INTO PUBLIC.PROVIDER_CORRELATION_MAPPINGS" in normalized:
            if self.existing_mapping is not None:
                return Cursor([])
            if self.mapping_row is not None:
                return Cursor([])
            self.mapping_row = row(mapping())
            return Cursor([self.mapping_row])
        if "FROM PUBLIC.PROVIDER_CORRELATION_MAPPINGS" in normalized:
            if "MAPPING_ID =" in normalized:
                candidates = [
                    value
                    for value in (
                        self.mapping_row,
                        row(self.existing_mapping) if self.existing_mapping else None,
                    )
                    if value is not None
                ]
                rows = [value for value in candidates if value[1] == params[-1]]
                return Cursor(rows)
            if self.existing_mapping is not None:
                return Cursor([row(self.existing_mapping)])
            return Cursor(self.resolution_rows)
        return Cursor([])


def register_kwargs() -> dict[str, object]:
    return {
        "mapping_id": "mapping-1",
        "provider": "razorpay",
        "connector_id": "razorpay-test",
        "provider_payment_id": "pay-1",
        "provider_order_id": "order-1",
        "merchant_reference": "merchant-ref-1",
        "incident_id": "incident-1",
        "case_id": "case-1",
        "related_order_reference": "merchant://orders/order-1",
        "related_payment_reference": "merchant://payments/pay-1",
        "mapping_source": "merchant_order_payment_context",
        "mapping_source_reference": "merchant://orders/order-1",
        "mapping_source_checksum": "sha256:trusted-mapping",
        "verified_at": NOW,
    }


def test_identical_mapping_registration_is_idempotent() -> None:
    connection = Connection()
    repository = ProviderCorrelationRepository(connection, context())

    first, first_inserted = repository.register(**register_kwargs())
    second, second_inserted = repository.register(**register_kwargs())

    assert first.mapping_id == second.mapping_id == "mapping-1"
    assert first_inserted is True
    assert second_inserted is False


def test_mapping_repository_uses_the_authoritative_public_schema() -> None:
    connection = Connection()
    repository = ProviderCorrelationRepository(connection, context())

    repository.register(**register_kwargs())

    assert any(
        "public.provider_correlation_mappings" in query.lower()
        for query, _ in connection.calls
    )


def test_mapping_identity_conflict_is_rejected() -> None:
    connection = Connection()
    repository = ProviderCorrelationRepository(connection, context())
    repository.register(**register_kwargs())

    conflicting = register_kwargs()
    conflicting["case_id"] = "case-2"
    with pytest.raises(
        ProviderCorrelationMappingConflictError, match="different content"
    ):
        repository.register(**conflicting)


def test_caller_user_cannot_provision_mapping_authority() -> None:
    repository = ProviderCorrelationRepository(Connection(), user_context())

    with pytest.raises(RepositoryError, match="service identity"):
        repository.register(**register_kwargs())


def test_identical_provider_identity_with_new_mapping_id_is_idempotent() -> None:
    existing = mapping()
    repository = ProviderCorrelationRepository(
        Connection(existing_mapping=existing), context()
    )

    duplicate = register_kwargs()
    duplicate["mapping_id"] = "mapping-2"
    value, inserted = repository.register(**duplicate)

    assert value == existing
    assert inserted is False


def test_provider_identity_collision_with_different_owner_is_rejected() -> None:
    existing = mapping()
    repository = ProviderCorrelationRepository(
        Connection(existing_mapping=existing), context()
    )

    conflicting = register_kwargs()
    conflicting["mapping_id"] = "mapping-2"
    conflicting["case_id"] = "case-2"
    with pytest.raises(
        ProviderCorrelationMappingConflictError, match="different content"
    ):
        repository.register(**conflicting)


def test_resolution_requires_one_mapping_matching_all_verified_identifiers() -> None:
    mapping_value = mapping()
    connection = Connection(mapping_value)
    repository = ProviderCorrelationRepository(connection, context())

    result = repository.resolve(correlation())

    assert result.resolved is True
    assert result.mapping == mapping_value
    query = connection.calls[-1][0]
    assert "WHERE CASE_ID" not in query.upper()
    assert "WHERE INCIDENT_ID" not in query.upper()


def test_resolution_fails_closed_for_mapping_collision_or_identifier_conflict() -> None:
    second = mapping(mapping_id="mapping-2", case_id="case-2", incident_id="incident-2")
    collision = ProviderCorrelationRepository(
        Connection(mapping(), second), context()
    ).resolve(correlation())
    assert collision.reason == "ambiguous_mapping"

    mismatch = ProviderCorrelationRepository(Connection(mapping()), context()).resolve(
        correlation(provider_order_id="order-other")
    )
    assert mismatch.reason == "mapping_conflict"


def test_mapping_dataclass_requires_authoritative_owner_fields() -> None:
    with pytest.raises(TypeError):
        ProviderCorrelationMapping(  # type: ignore[call-arg]
            tenant_id="tenant-a",
            mapping_id="mapping-1",
        )
