"""Typed, idempotent RECLAIM API boundary used by n8n.

n8n owns durable execution and retry scheduling.  This service owns tenant,
case, stage, and idempotency validation and persists the authoritative result
through PostgreSQL.  It never accepts arbitrary commands from a workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from packages.contracts.case_inbox import OrchestrationStage
from packages.contracts.orchestration import (
    NormalizedIntakeResponse,
    OrchestrationOutcome,
    OrchestrationRecoveryRequest,
    OrchestrationStageRequest,
    StartOrchestrationRunRequest,
)

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext
from app.db.repositories.base import RepositoryError
from app.db.repositories.orchestration import OrchestrationRunRecord
from app.db.unit_of_work import PostgresUnitOfWork


class OrchestrationServiceError(RuntimeError):
    """Raised when a typed orchestration request cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class OrchestrationResponse:
    tenant_id: str
    case_id: str
    run_id: str
    workflow_version: str
    external_execution_id: str
    stage: OrchestrationStage
    status: str
    failure_code: str | None = None


class OrchestrationService:
    """Application service for human starts and n8n stage callbacks."""

    ALLOWED_FAILURE_CODES = frozenset(
        {
            "empty_timeline",
            "model_unavailable",
            "normalize_failed",
            "policy_failed",
            "timeout",
            "upstream_unavailable",
            "unknown_result",
        }
    )
    ALLOWED_CASE_STATES = frozenset(
        {
            "intake_received",
            "collecting_evidence",
            "timeline_ready",
            "analyzed",
            "action_pending",
            "containing",
        }
    )

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[TenantAuthorizationContext], PostgresUnitOfWork],
        id_factory: Callable[[], str] | None = None,
        workflow_version: str = "incident-analysis-handoff.v1",
    ) -> None:
        self.unit_of_work_factory = unit_of_work_factory
        self.id_factory = id_factory or (lambda: f"orchestration-run:{uuid4().hex}")
        self.workflow_version = workflow_version

    def start_run(
        self,
        *,
        tenant_id: str,
        case_id: str,
        request: StartOrchestrationRunRequest,
        authorization_context: TenantAuthorizationContext,
    ) -> OrchestrationResponse:
        _require_tenant(tenant_id, authorization_context)
        _require_start_role(authorization_context)
        _require_expected_state(request.expected_state, self.ALLOWED_CASE_STATES)
        if request.workflow_version != self.workflow_version:
            raise OrchestrationServiceError("workflow version is not allowlisted")
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            self._require_case(
                unit_of_work,
                tenant_id=tenant_id,
                case_id=case_id,
                expected_state=request.expected_state,
            )
            try:
                record = unit_of_work.orchestration.create_or_get(
                    run_id=self.id_factory(),
                    case_id=case_id,
                    workflow_version=request.workflow_version,
                    external_execution_id=request.external_execution_id,
                    idempotency_key=request.idempotency_key,
                )
            except RepositoryError as exc:
                raise OrchestrationServiceError(str(exc)) from exc
        return _response(record)

    def claim_run(
        self,
        *,
        tenant_id: str,
        case_id: str,
        run_id: str,
        expected_state: str,
        external_execution_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> OrchestrationResponse:
        _require_tenant(tenant_id, authorization_context)
        _require_n8n_role(authorization_context)
        _require_expected_state(expected_state, self.ALLOWED_CASE_STATES)
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            record = unit_of_work.orchestration.get(run_id=run_id)
            if record is None or record.case_id != case_id:
                raise OrchestrationServiceError("orchestration run is not present for this case")
            self._require_case(
                unit_of_work,
                tenant_id=tenant_id,
                case_id=case_id,
                expected_state=expected_state,
            )
            try:
                claimed = unit_of_work.orchestration.claim(
                    run_id=run_id,
                    external_execution_id=external_execution_id,
                )
            except RepositoryError as exc:
                raise OrchestrationServiceError(str(exc)) from exc
        return _response(claimed)

    def record_stage(
        self,
        *,
        tenant_id: str,
        case_id: str,
        run_id: str,
        stage: OrchestrationStage,
        request: OrchestrationStageRequest,
        authorization_context: TenantAuthorizationContext,
    ) -> OrchestrationResponse:
        _require_tenant(tenant_id, authorization_context)
        _require_n8n_role(authorization_context)
        _require_expected_state(request.expected_state, self.ALLOWED_CASE_STATES)
        if (
            request.failure_code is not None
            and request.failure_code not in self.ALLOWED_FAILURE_CODES
        ):
            raise OrchestrationServiceError("failure code is not allowlisted")
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            record = unit_of_work.orchestration.get(run_id=run_id)
            if record is None or record.case_id != case_id:
                raise OrchestrationServiceError("orchestration run is not present for this case")
            try:
                updated = unit_of_work.orchestration.advance_stage(
                    run_id=run_id,
                    stage=stage,
                    expected_state=request.expected_state,
                    idempotency_key=request.idempotency_key,
                    outcome=request.outcome,
                    failure_code=request.failure_code,
                )
            except RepositoryError as exc:
                raise OrchestrationServiceError(str(exc)) from exc
        return _response(updated)

    def get_run(
        self,
        *,
        tenant_id: str,
        case_id: str,
        run_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> OrchestrationResponse:
        _require_tenant(tenant_id, authorization_context)
        authorization_context.require_role(RequiredRole.REVIEWER)
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            record = unit_of_work.orchestration.get(run_id=run_id)
        if record is None or record.case_id != case_id:
            raise OrchestrationServiceError("orchestration run is not present for this case")
        return _response(record)

    def normalize_intake(
        self,
        *,
        tenant_id: str,
        case_id: str,
        run_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> NormalizedIntakeResponse:
        """Return only structured, redacted intake context to n8n."""

        _require_tenant(tenant_id, authorization_context)
        _require_n8n_role(authorization_context)
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            run = unit_of_work.orchestration.get(run_id=run_id)
            if run is None or run.case_id != case_id:
                raise OrchestrationServiceError("orchestration run is not present for this case")
            incident = unit_of_work.incidents.get(
                incident_id=self._incident_id(unit_of_work, case_id)
            )
            if incident is None:
                raise OrchestrationServiceError("incident is not present for this case")
            timeline = unit_of_work.timeline.for_case(case_id=case_id)
        status = "normalized" if timeline else "empty_timeline"
        return NormalizedIntakeResponse(
            tenant_id=tenant_id,
            case_id=case_id,
            run_id=run_id,
            status=status,
            incident_type=str(incident[10] or "other"),
            occurred_at=(incident[11] or incident[4]).isoformat(),
            report_reference=None if incident[6] is None else str(incident[6]),
            narrative_checksum=None if incident[12] is None else str(incident[12]),
            identifiers={
                key: str(value)
                for key, value in {
                    "customer_reference": incident[13],
                    "account_reference": incident[14],
                    "order_reference": incident[15],
                    "payment_reference": incident[16],
                    "external_reference": incident[19],
                }.items()
                if value is not None
            },
        )

    def recover(
        self,
        *,
        tenant_id: str,
        case_id: str,
        request: OrchestrationRecoveryRequest,
        authorization_context: TenantAuthorizationContext,
    ) -> OrchestrationResponse:
        """Persist a bounded attention outcome from the n8n error workflow."""

        _require_tenant(tenant_id, authorization_context)
        _require_n8n_role(authorization_context)
        _require_expected_state(request.expected_state, self.ALLOWED_CASE_STATES)
        if request.failure_code not in self.ALLOWED_FAILURE_CODES:
            raise OrchestrationServiceError("failure code is not allowlisted")
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            run = unit_of_work.orchestration.get(run_id=request.run_id)
            if run is None or run.case_id != case_id:
                raise OrchestrationServiceError("orchestration run is not present for this case")
            if run.external_execution_id != request.external_execution_id:
                raise OrchestrationServiceError("n8n execution identity does not match the run")
            try:
                updated = unit_of_work.orchestration.advance_stage(
                    run_id=request.run_id,
                    stage=OrchestrationStage.ANALYZE,
                    expected_state=request.expected_state,
                    idempotency_key=request.idempotency_key,
                    outcome=OrchestrationOutcome.REQUIRES_ATTENTION,
                    failure_code=request.failure_code,
                )
            except RepositoryError as exc:
                raise OrchestrationServiceError(str(exc)) from exc
        return _response(updated)

    @staticmethod
    def _require_case(
        unit_of_work: PostgresUnitOfWork,
        *,
        tenant_id: str,
        case_id: str,
        expected_state: str,
    ) -> None:
        case = unit_of_work.cases.get(case_id=case_id)
        if case is None or str(case[0]) != tenant_id or str(case[1]) != case_id:
            raise OrchestrationServiceError("case is not present in authoritative PostgreSQL")
        if str(case[3]) != expected_state:
            raise OrchestrationServiceError("case state does not match expected_state")

    @staticmethod
    def _incident_id(unit_of_work: PostgresUnitOfWork, case_id: str) -> str:
        case = unit_of_work.cases.get(case_id=case_id)
        if case is None:
            raise OrchestrationServiceError("case is not present in authoritative PostgreSQL")
        return str(case[2])


def _response(record: OrchestrationRunRecord) -> OrchestrationResponse:
    return OrchestrationResponse(
        tenant_id=record.tenant_id,
        case_id=record.case_id,
        run_id=record.run_id,
        workflow_version=record.workflow_version,
        external_execution_id=record.external_execution_id,
        stage=record.stage,
        status=record.status.value,
        failure_code=record.failure_code,
    )


def _require_tenant(tenant_id: str, context: TenantAuthorizationContext) -> None:
    if context.tenant_id != tenant_id:
        raise OrchestrationServiceError("request tenant does not match authorization context")


def _require_start_role(context: TenantAuthorizationContext) -> None:
    if (
        RequiredRole.REVIEWER.value in context.roles
        or RequiredRole.ORCHESTRATOR.value in context.roles
    ):
        return
    raise OrchestrationServiceError("identity cannot start orchestration")


def _require_n8n_role(context: TenantAuthorizationContext) -> None:
    if context.identity_type is not IdentityType.SERVICE:
        raise OrchestrationServiceError("only the n8n service identity may advance orchestration")
    if RequiredRole.ORCHESTRATOR.value not in context.roles:
        raise OrchestrationServiceError("service identity is not the n8n orchestrator")


def _require_expected_state(value: str, allowlisted: frozenset[str]) -> None:
    if value not in allowlisted:
        raise OrchestrationServiceError("orchestration expected_state is not allowlisted")


__all__ = ["OrchestrationResponse", "OrchestrationService", "OrchestrationServiceError"]
