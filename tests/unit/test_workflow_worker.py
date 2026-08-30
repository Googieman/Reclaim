"""Worker registration tests for the production US1 Temporal path."""

from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.storage.minio_evidence import ImmutableEvidenceStore
from connectors.simulators.evidence import build_default_evidence_simulators
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from timeline.reconstruct import TimelineReconstructor
from workflows.worker import CaseWorkerDependencies, make_case_workflow_activities


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="workflow-worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def test_worker_registers_every_production_us1_activity() -> None:
    dependencies = CaseWorkerDependencies(
        unit_of_work_factory=lambda _context: None,  # type: ignore[arg-type]
        authorization_context_factory=context,
        evidence_orchestrator=EvidenceOrchestrator(build_default_evidence_simulators()),
        evidence_storage=EvidenceStorage(ImmutableEvidenceStore(InMemoryObjectStorage())),
        timeline_reconstructor=TimelineReconstructor(),
    )

    activities = make_case_workflow_activities(dependencies)
    names = {
        activity.__dict__["__temporal_activity_definition"].name
        for activity in activities
    }

    assert names == {
        "case.read_authoritative_state",
        "case.start_intake",
        "case.recover_authoritative_state",
        "case.collect_evidence",
        "case.rebuild_timeline",
    }
