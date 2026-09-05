"""Production Temporal worker wiring for the completed US1 workflow stages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage
from temporalio.client import Client
from temporalio.worker import Worker
from timeline.reconstruct import TimelineReconstructor

from workflows.activities import (
    AgentAnalysisActivityDependencies,
    ContainmentActivityDependencies,
    EvidenceActivityDependencies,
    IntakeActivityDependencies,
    TimelineActivityDependencies,
    make_agent_analysis_activities,
    make_containment_activities,
    make_evidence_activities,
    make_intake_activities,
    make_timeline_activities,
)
from workflows.case_workflow import CaseWorkflow

DEFAULT_TASK_QUEUE = "reclaim-case-workflows"
UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
AuthorizationContextFactory = Callable[[str], TenantAuthorizationContext]


@dataclass(frozen=True, slots=True)
class CaseWorkerDependencies:
    """Application-owned dependencies supplied to the trusted worker process."""

    unit_of_work_factory: UnitOfWorkFactory
    authorization_context_factory: AuthorizationContextFactory
    evidence_orchestrator: EvidenceOrchestrator
    evidence_storage: EvidenceStorage
    timeline_reconstructor: TimelineReconstructor
    evidence_request_factory: Callable[[Any], tuple[Any, ...]] | None = None
    containment_runner: Callable[[Any], Any] | None = None
    agent_runner: Callable[[Any], Any] | None = None


def make_case_workflow_activities(
    dependencies: CaseWorkerDependencies,
) -> tuple[Any, ...]:
    """Return every production activity required by CaseWorkflow's US1 path."""

    intake = make_intake_activities(
        IntakeActivityDependencies(
            unit_of_work_factory=dependencies.unit_of_work_factory,
            authorization_context_factory=dependencies.authorization_context_factory,
        )
    )
    evidence = make_evidence_activities(
        EvidenceActivityDependencies(
            orchestrator=dependencies.evidence_orchestrator,
            authorization_context_factory=dependencies.authorization_context_factory,
            request_factory=dependencies.evidence_request_factory,
        )
    )
    timeline = make_timeline_activities(
        TimelineActivityDependencies(
            reconstructor=dependencies.timeline_reconstructor,
            evidence_storage=dependencies.evidence_storage,
            unit_of_work_factory=dependencies.unit_of_work_factory,
            authorization_context_factory=dependencies.authorization_context_factory,
        )
    )
    activities = [
        intake.read_authoritative_state,
        intake.start_intake,
        intake.recover_authoritative_state,
        evidence.collect_evidence,
        timeline.rebuild_timeline,
    ]
    if dependencies.containment_runner is not None:
        containment = make_containment_activities(
            ContainmentActivityDependencies(
                authorization_context_factory=dependencies.authorization_context_factory,
                runner=dependencies.containment_runner,
            )
        )
        activities.append(containment.run_containment_activity)
    if dependencies.agent_runner is not None:
        agent = make_agent_analysis_activities(
            AgentAnalysisActivityDependencies(
                authorization_context_factory=dependencies.authorization_context_factory,
                runner=dependencies.agent_runner,
            )
        )
        activities.append(agent.analyze_case)
    return tuple(activities)


def create_case_worker(
    client: Client,
    dependencies: CaseWorkerDependencies,
    *,
    task_queue: str = DEFAULT_TASK_QUEUE,
    workflow_runner: Any | None = None,
) -> Worker:
    """Create a worker that registers the real US1 activities with CaseWorkflow."""

    if not task_queue.strip():
        raise ValueError("workflow task queue is required")
    kwargs: dict[str, Any] = {
        "client": client,
        "task_queue": task_queue,
        "workflows": [CaseWorkflow],
        "activities": list(make_case_workflow_activities(dependencies)),
    }
    if workflow_runner is not None:
        kwargs["workflow_runner"] = workflow_runner
    return Worker(**kwargs)


__all__ = [
    "CaseWorkerDependencies",
    "DEFAULT_TASK_QUEUE",
    "create_case_worker",
    "make_case_workflow_activities",
]
