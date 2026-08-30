"""Temporal activity boundary tests for evidence collection."""

from datetime import UTC, datetime

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.storage.minio_evidence import ImmutableEvidenceStore
from connectors.simulators.evidence import build_default_evidence_simulators
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from temporalio.exceptions import ApplicationError
from workflows.activities.evidence import (
    EvidenceActivityDependencies,
    make_evidence_activities,
)
from workflows.commands import CaseWorkflowCommand


def context(tenant_id: str = "tenant-a", *, service: bool = True):
    principal = AuthenticatedPrincipal(
        subject="workflow-worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE if service else IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def command() -> CaseWorkflowCommand:
    return CaseWorkflowCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("collect_evidence",),
    )


def activities():
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=EvidenceStorage(ImmutableEvidenceStore(InMemoryObjectStorage())),
    )
    return make_evidence_activities(
        EvidenceActivityDependencies(
            orchestrator=orchestrator,
            authorization_context_factory=context,
            request_factory=lambda value: orchestrator.requests_for_case(
                tenant_id=value.tenant_id,
                case_id=value.case_id,
                correlation_id=value.correlation_id,
                requested_at=datetime(2026, 8, 30, 10, 1, tzinfo=UTC),
            ),
        )
    )


@pytest.mark.asyncio
async def test_evidence_activity_returns_authoritative_collection_summary() -> None:
    result = await activities().collect_evidence(command())

    assert result["tenant_id"] == "tenant-a"
    assert result["case_id"] == "case-1"
    assert result["authoritative"] is True
    assert result["evidence_count"] == 6
    assert result["normalized_fact_count"] == 6


@pytest.mark.asyncio
async def test_evidence_activity_rejects_non_service_worker_context() -> None:
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=EvidenceStorage(ImmutableEvidenceStore(InMemoryObjectStorage())),
    )
    evidence_activities = make_evidence_activities(
        EvidenceActivityDependencies(
            orchestrator=orchestrator,
            authorization_context_factory=lambda _: context(service=False),
        )
    )

    with pytest.raises(ApplicationError, match="tenant-bound") as error:
        await evidence_activities.collect_evidence(command())
    assert error.value.non_retryable is True
