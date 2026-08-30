"""Temporal evidence activity backed by the tenant-scoped evidence orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from evidence.orchestrator import EvidenceOrchestrator
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.commands import CaseWorkflowCommand

AuthorizationContextFactory = Callable[[str], TenantAuthorizationContext]
EvidenceRequestFactory = Callable[[CaseWorkflowCommand], tuple[Any, ...]]


@dataclass(frozen=True, slots=True)
class EvidenceActivityDependencies:
    """Trusted worker wiring; the activity cannot derive authorization from command data."""

    orchestrator: EvidenceOrchestrator
    authorization_context_factory: AuthorizationContextFactory
    request_factory: EvidenceRequestFactory | None = None


class EvidenceActivities:
    """Run collection as a durable activity while PostgreSQL remains authoritative."""

    def __init__(self, dependencies: EvidenceActivityDependencies) -> None:
        self.dependencies = dependencies

    @activity.defn(name="case.collect_evidence")
    async def collect_evidence(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        context = self.dependencies.authorization_context_factory(command.tenant_id)
        if (
            not isinstance(context, TenantAuthorizationContext)
            or context.tenant_id != command.tenant_id
            or context.identity_type is not IdentityType.SERVICE
        ):
            raise ApplicationError(
                "evidence activity service context is not tenant-bound",
                non_retryable=True,
            )
        requests = (
            self.dependencies.request_factory(command)
            if self.dependencies.request_factory is not None
            else self.dependencies.orchestrator.requests_for_case(
                tenant_id=command.tenant_id,
                case_id=command.case_id,
                correlation_id=command.correlation_id,
                requested_at=datetime.now(UTC),
            )
        )
        try:
            result = self.dependencies.orchestrator.collect(
                case_id=command.case_id,
                requests=requests,
                authorization_context=context,
            )
        except (ValueError, PermissionError) as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc
        except Exception as exc:
            raise ApplicationError("evidence collection activity failed") from exc
        return {
            "tenant_id": result.tenant_id,
            "case_id": result.case_id,
            "state": "collecting_evidence",
            "authoritative": result.authoritative_store == "postgresql",
            "evidence_count": len(result.items),
            "normalized_fact_count": len(result.normalized_facts),
            "uncertainty": result.uncertainty,
            "provenance_count": len(result.provenance),
        }


def make_evidence_activities(dependencies: EvidenceActivityDependencies) -> EvidenceActivities:
    """Build the activity object to register with a Temporal worker."""

    return EvidenceActivities(dependencies)


__all__ = [
    "EvidenceActivities",
    "EvidenceActivityDependencies",
    "make_evidence_activities",
]
