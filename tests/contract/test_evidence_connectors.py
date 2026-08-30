"""Contract coverage for approved read-only evidence connectors and simulators."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType, TenantAuthorizationError
from app.contracts.registry import ContractCompatibilityError, validate_manifest
from app.storage.minio_evidence import checksum_for_bytes
from connectors.evidence.base import EvidenceReadResult, ReadOnlyEvidenceAdapter
from connectors.simulators.evidence import (
    DeterministicEvidenceSimulator,
    EvidenceSimulatorScenario,
)
from pydantic import ValidationError

from packages.contracts.connectors import (
    ConnectorFailureState,
    ConnectorLimits,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
    EvidenceRequest,
    EvidenceResponse,
)

EVIDENCE_RESOURCES = (
    "sessions",
    "devices",
    "profile_changes",
    "orders",
    "fulfillment",
    "payments",
)
ROOT = Path(__file__).resolve().parents[2]


def make_manifest(
    resource: str = "sessions",
    *,
    mode: ConnectorMode = ConnectorMode.SIMULATOR,
    **overrides: object,
) -> ConnectorManifest:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-evidence-1",
        "connector_id": f"{resource}-{mode.value}",
        "contract_version": "1.0.0",
        "connector_type": ConnectorType.EVIDENCE,
        "mode": mode,
        "resources": (resource,),
        "operations": ("read",),
        "auth_scope": (f"merchant:{resource}:read",),
        "request_schema": f"evidence.{resource}.request.v1",
        "response_schema": f"evidence.{resource}.response.v1",
        "timestamp_semantics": "observed_at is source time; collected_at is receipt time",
        "idempotency_behavior": "duplicate reads are replay-safe",
        "failure_states": tuple(ConnectorFailureState),
    }
    values.update(overrides)
    return ConnectorManifest(**values)


def make_response(**overrides: object) -> EvidenceResponse:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-evidence-1",
        "case_id": "case-1",
        "connector_id": "sessions-simulator",
        "source_identity": "merchant-session-store",
        "resource_type": "sessions",
        "observed_at": datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
        "collected_at": datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
        "completeness": "complete",
        "raw_artifact_reference": "minio://tenants/tenant-a/case-1/session.json",
        "raw_checksum": "sha256:raw-session",
        "normalized_facts": [{"session_id": "s-1"}],
        "connector_status": "complete",
    }
    values.update(overrides)
    return EvidenceResponse(**values)


@pytest.mark.parametrize("resource", EVIDENCE_RESOURCES)
def test_each_approved_resource_has_a_tenant_scoped_read_only_manifest(
    resource: str,
) -> None:
    manifest = validate_manifest(make_manifest(resource))

    assert manifest.tenant_id == "tenant-a"
    assert manifest.resources == (resource,)
    assert manifest.operations == ("read",)
    assert manifest.mode is ConnectorMode.SIMULATOR


def test_live_and_simulator_declarations_share_versioned_schema_and_allowlist() -> None:
    simulator = make_manifest("payments", mode=ConnectorMode.SIMULATOR)
    live = make_manifest("payments", mode=ConnectorMode.LIVE)

    assert validate_manifest(simulator).model_dump(
        exclude={"mode", "connector_id", "correlation_id"}
    ) == validate_manifest(live).model_dump(
        exclude={"mode", "connector_id", "correlation_id"}
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("operations", ("write",), "read-only"),
        ("resources", ("customer_secrets",), "allowlisted"),
        ("operations", ("read", "*"), "wildcard"),
        ("resources", ("*",), "wildcard"),
    ),
)
def test_manifest_rejects_mutating_unapproved_or_wildcard_authority(
    field: str, value: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ContractCompatibilityError, match=message):
        validate_manifest(make_manifest(**{field: value}))


@pytest.mark.parametrize("failure_state", tuple(ConnectorFailureState))
def test_evidence_response_preserves_declared_failure_state(
    failure_state: ConnectorFailureState,
) -> None:
    response = make_response(
        completeness="partial",
        connector_status=failure_state.value,
        failure_state=failure_state,
    )

    assert response.failure_state is failure_state
    assert response.untrusted is True
    assert response.raw_checksum == "sha256:raw-session"


def test_partial_evidence_defaults_to_partial_failure_without_inventing_facts() -> None:
    response = make_response(
        completeness="partial",
        connector_status="partial",
        normalized_facts=[],
    )

    assert response.failure_state is ConnectorFailureState.PARTIAL
    assert response.normalized_facts == []


def test_evidence_request_is_case_and_tenant_scoped_with_bounded_read_parameters() -> (
    None
):
    request = EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-evidence-1",
        case_id="case-1",
        connector_id="payments-simulator",
        resource_type="payments",
        resource_ids=("payment-1",),
        requested_at=datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
        page_size=50,
    )

    assert request.operation == "read"
    assert request.resource_ids == ("payment-1",)
    assert request.page_size == 50

    with pytest.raises(ValidationError):
        EvidenceRequest(
            tenant_id="tenant-a",
            correlation_id="corr-evidence-1",
            case_id="case-1",
            connector_id="payments-simulator",
            resource_type="payments",
            requested_at=datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
            page_size=10_001,
        )


def test_manifest_limits_are_explicit_and_connector_statuses_are_closed_set() -> None:
    limits = ConnectorLimits(
        max_page_size=250, timeout_seconds=30, max_payload_bytes=4096
    )
    manifest = make_manifest(limits=limits)

    assert manifest.limits.max_page_size == 250
    assert manifest.limits.max_payload_bytes == 4096
    assert set(manifest.failure_states) == set(ConnectorFailureState)


def authorized_context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="evidence-worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def request_for(resource: str, connector_id: str) -> EvidenceRequest:
    return EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-evidence-1",
        case_id="case-1",
        connector_id=connector_id,
        resource_type=resource,
        requested_at=datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
    )


def test_adapter_requires_authenticated_context_and_cannot_mutate() -> None:
    response = make_response(connector_id="sessions-read")
    adapter = ReadOnlyEvidenceAdapter(
        make_manifest("sessions", connector_id="sessions-read"),
        reader=lambda _: EvidenceReadResult(response, b"raw"),
    )

    with pytest.raises(TenantAuthorizationError):
        adapter.read(
            request_for("sessions", "sessions-read"), authorization_context=None
        )  # type: ignore[arg-type]
    assert not hasattr(adapter, "write")
    assert not hasattr(adapter, "execute")


@pytest.mark.parametrize(
    "scenario",
    tuple(EvidenceSimulatorScenario),
)
def test_deterministic_simulator_uses_the_contract_for_every_failure_state(
    scenario: EvidenceSimulatorScenario,
) -> None:
    simulator = DeterministicEvidenceSimulator.for_resource(
        "tenant-a",
        "sessions",
        scenario=scenario,
        fixture_directory=ROOT / "tests" / "fixtures" / "evidence" / "variants",
    )

    result = simulator.read(
        request_for("sessions", "sim-sessions"),
        authorization_context=authorized_context(),
    )

    assert result.response.tenant_id == "tenant-a"
    assert result.response.raw_checksum == checksum_for_bytes(result.raw_payload)
    assert result.provenance["mode"] == "replay"
    if scenario in {
        EvidenceSimulatorScenario.TIMEOUT,
        EvidenceSimulatorScenario.UNAVAILABLE,
        EvidenceSimulatorScenario.INVALID,
    }:
        assert result.response.normalized_facts == []
    if scenario is EvidenceSimulatorScenario.DUPLICATE:
        assert len(result.response.normalized_facts) == 2


def test_simulator_rejects_a_request_from_another_tenant() -> None:
    simulator = DeterministicEvidenceSimulator.for_resource("tenant-a", "sessions")
    request = request_for("sessions", "sim-sessions").model_copy(
        update={"tenant_id": "tenant-b"}
    )

    with pytest.raises(TenantAuthorizationError):
        simulator.read(request, authorization_context=authorized_context("tenant-b"))
