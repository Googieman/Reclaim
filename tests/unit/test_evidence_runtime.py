"""Evidence orchestration, provenance, failure, and tenant-boundary tests."""

from datetime import UTC, datetime

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType, TenantAuthorizationError
from app.storage.minio_evidence import ImmutableEvidenceStore
from connectors.simulators.evidence import (
    EvidenceSimulatorScenario,
    build_default_evidence_simulators,
)
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from packages.contracts.connectors import EvidenceRequest


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def requests(orchestrator: EvidenceOrchestrator) -> tuple[EvidenceRequest, ...]:
    return orchestrator.requests_for_case(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        requested_at=datetime(2026, 8, 30, 10, 1, tzinfo=UTC),
    )


def storage() -> EvidenceStorage:
    return EvidenceStorage(ImmutableEvidenceStore(InMemoryObjectStorage()))


def test_collection_is_order_independent_and_persists_verified_provenance() -> None:
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=storage(),
    )

    first = orchestrator.collect(
        case_id="case-1",
        requests=tuple(reversed(requests(orchestrator))),
        authorization_context=context(),
    )
    second = orchestrator.collect(
        case_id="case-1",
        requests=requests(orchestrator),
        authorization_context=context(),
    )

    assert first.items == second.items
    assert first.normalized_facts == second.normalized_facts
    assert first.provenance == second.provenance
    assert len(first.items) == 6
    assert len(first.normalized_facts) == 6
    assert all(item.integrity_status == "verified" for item in first.items)
    assert all(item.raw_checksum == item.expected_checksum for item in first.items)
    assert all(item.untrusted for item in first.items)
    assert {item.evidence_id for item in first.items} == {
        item.provenance.evidence_id for item in first.items if item.provenance
    }


def test_duplicate_requests_converge_to_one_evidence_item() -> None:
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=storage(),
    )
    request = requests(orchestrator)[0]
    result = orchestrator.collect(
        case_id="case-1",
        requests=(request, request),
        authorization_context=context(),
    )

    assert len(result.items) == 1
    assert len(result.normalized_facts) == 1


def test_unavailable_connector_is_recorded_without_inventing_facts() -> None:
    connectors = build_default_evidence_simulators(
        "tenant-a",
        scenarios={"payments": EvidenceSimulatorScenario.UNAVAILABLE},
    )
    orchestrator = EvidenceOrchestrator(connectors, storage=storage())
    result = orchestrator.collect(
        case_id="case-1",
        requests=requests(orchestrator),
        authorization_context=context(),
    )
    payment = next(item for item in result.items if item.resource_type == "payments")

    assert payment.normalized_facts == ()
    assert payment.collection_error is not None
    assert "unavailable" in payment.collection_error
    assert len(result.normalized_facts) == 5
    assert any("sim-payments" in value for value in result.uncertainty)


def test_missing_connector_is_recorded_as_unavailable() -> None:
    orchestrator = EvidenceOrchestrator({}, storage=storage())
    request = EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        connector_id="payments-not-configured",
        resource_type="payments",
        requested_at=datetime(2026, 8, 30, 10, 1, tzinfo=UTC),
    )

    result = orchestrator.collect(
        case_id="case-1",
        requests=(request,),
        authorization_context=context(),
    )

    assert result.items[0].normalization_status == "not_attempted"
    assert result.items[0].normalized_facts == ()
    assert result.items[0].raw_object_uri is not None


def test_collection_never_uses_request_tenant_as_authority() -> None:
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=storage(),
    )
    request = requests(orchestrator)[0].model_copy(update={"tenant_id": "tenant-b"})

    with pytest.raises(TenantAuthorizationError):
        orchestrator.collect(
            case_id="case-1",
            requests=(request,),
            authorization_context=context("tenant-b"),
        )
