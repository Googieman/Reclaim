"""Production-shaped application dependency assembly.

This module wires authoritative services but does not create credentials or
perform external actions.  Deployment supplies the connection factories and
verified OIDC implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import TenantAuthorizationContext
from app.cases.inbox import CaseInboxService
from app.config import Settings
from app.db.unit_of_work import PostgresUnitOfWork
from app.intake.service import IncidentIntakeService
from app.orchestration.service import OrchestrationService
from app.storage.minio_evidence import ImmutableEvidenceStore

ConnectionFactory = Callable[[], Any]


@dataclass(slots=True)
class HostedRuntime:
    settings: Settings
    connection_factory: ConnectionFactory
    oidc_verifier: Any
    intake_service: IncidentIntakeService | None
    case_inbox_service: CaseInboxService | None
    orchestration_service: OrchestrationService | None

    def unit_of_work_factory(self, context: TenantAuthorizationContext) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(
            self.connection_factory,
            authorization_context=context,
        )

    def check_readiness(self) -> None:
        connection = self.connection_factory()
        try:
            result = connection.execute("SELECT 1")
            row = result.fetchone()
            if row != (1,):
                raise RuntimeError("authoritative PostgreSQL readiness probe failed")
        finally:
            connection.close()


def build_hosted_runtime(
    settings: Settings,
    *,
    connection_factory: ConnectionFactory,
    oidc_verifier: Any,
) -> HostedRuntime:
    if settings.demo_read_only_enabled or settings.authoritative_demo_enabled:
        raise ValueError("hosted runtime cannot enable a local demo")
    if settings.live_actions_enabled or settings.live_financial_actions_enabled:
        raise ValueError("hosted runtime requires live actions to remain disabled")
    if oidc_verifier is None:
        raise ValueError("hosted runtime requires a verified OIDC implementation")
    evidence_store = ImmutableEvidenceStore.from_endpoint(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        bucket="reclaim-evidence",
    )
    runtime = HostedRuntime(
        settings=settings,
        connection_factory=connection_factory,
        oidc_verifier=oidc_verifier,
        intake_service=None,
        case_inbox_service=None,
        orchestration_service=None,
    )
    runtime.intake_service = IncidentIntakeService(
        unit_of_work_factory=runtime.unit_of_work_factory,
        raw_report_store=evidence_store,
        max_report_bytes=settings.incident_report_max_bytes,
    )
    runtime.case_inbox_service = CaseInboxService(
        unit_of_work_factory=runtime.unit_of_work_factory
    )
    runtime.orchestration_service = OrchestrationService(
        unit_of_work_factory=runtime.unit_of_work_factory,
        workflow_version=settings.n8n_workflow_version,
    )
    return runtime
