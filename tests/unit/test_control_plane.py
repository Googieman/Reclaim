"""Declaration-only control-plane registry tests."""

from app.control_plane.registry import ConnectorDeclaration, ConnectorRegistry
from app.control_plane.tenant_config import (
    StaticTenantConfigurationSource,
    TenantConfiguration,
    TenantConfigurationBoundary,
)

from packages.contracts.connectors import (
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)


def manifest() -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        connector_id="payments-read",
        contract_version="1.0.0",
        connector_type=ConnectorType.EVIDENCE,
        mode=ConnectorMode.SIMULATOR,
        resources=("payments",),
        operations=("read",),
        auth_scope=("tenant-a:evidence:payments:read",),
        request_schema="EvidenceRequest",
        response_schema="EvidenceResponse",
        timestamp_semantics="provider_observed_and_collection_utc",
        idempotency_behavior="stable_request_identity",
        failure_states=("partial", "unavailable"),
    )


def test_registry_exposes_declarations_and_tenant_configuration_only() -> None:
    registry = ConnectorRegistry(
        [ConnectorDeclaration("tenant-a", "payments-read", manifest())]
    )
    source = StaticTenantConfigurationSource(
        [TenantConfiguration("tenant-a", frozenset({"payments-read"}), "policy-1")]
    )
    boundary = TenantConfigurationBoundary(source)

    assert registry.allows(
        tenant_id="tenant-a", connector_id="payments-read", operation="read"
    )
    assert not registry.allows(
        tenant_id="tenant-a", connector_id="payments-read", operation="write"
    )
    assert boundary.connector_enabled(
        tenant_id="tenant-a", connector_id="payments-read"
    )
    assert boundary.action_mode("tenant-a") == "replay"
    assert not hasattr(
        registry.get(tenant_id="tenant-a", connector_id="payments-read"), "client"
    )
