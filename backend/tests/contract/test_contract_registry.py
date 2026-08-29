
import pytest
from app.contracts.registry import ContractCompatibilityError, ContractRegistry
from packages.contracts.connectors import ConnectorManifest, ConnectorMode, ConnectorType


def manifest(**overrides: object) -> ConnectorManifest:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "connector_id": "payments-read",
        "contract_version": "1.0.0",
        "connector_type": ConnectorType.EVIDENCE,
        "mode": ConnectorMode.SIMULATOR,
        "resources": ("payments",),
        "operations": ("read",),
        "auth_scope": ("tenant-a:evidence:payments:read",),
        "request_schema": "EvidenceRequest",
        "response_schema": "EvidenceResponse",
        "timestamp_semantics": "provider_observed_and_collection_utc",
        "idempotency_behavior": "stable_request_identity",
        "failure_states": ("partial", "unavailable", "timeout"),
    }
    values.update(overrides)
    if "tenant_id" in overrides or "auth_scope" in overrides:
        return ConnectorManifest.model_construct(**values)
    return ConnectorManifest(**values)


def test_registers_only_explicit_tenant_scoped_read_connector() -> None:
    registry = ContractRegistry()
    registered = registry.register(manifest())

    assert registered.connector_id == "payments-read"
    assert registry.get("tenant-a", "payments-read") is registered
    assert registry.for_tenant("tenant-a") == (registered,)
    assert not registry.contains("tenant-b", "payments-read")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"tenant_id": ""}, "tenant scope"),
        ({"operations": ("*",)}, "wildcard"),
        ({"auth_scope": ()}, "auth scope"),
        ({"contract_version": "2.0.0"}, "incompatible"),
        ({"operations": ("write",)}, "read-only"),
    ],
)
def test_rejects_unsafe_or_incompatible_manifests(
    overrides: dict[str, object], message: str
) -> None:
    registry = ContractRegistry()
    candidate = manifest(**overrides)
    with pytest.raises(ContractCompatibilityError, match=message):
        registry.register(candidate)


def test_action_manifest_is_limited_to_named_operations() -> None:
    action = manifest(
        connector_id="session-actions",
        connector_type=ConnectorType.ACTION,
        resources=("sessions",),
        operations=("revoke_suspicious_session",),
        auth_scope=("tenant-a:actions:sessions:revoke",),
        failure_states=("unknown_result", "timeout"),
    )
    assert ContractRegistry().register(action).connector_type is ConnectorType.ACTION
