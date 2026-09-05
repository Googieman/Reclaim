"""PostgreSQL-backed localhost product flow.

This module is the deliberately small application boundary used by the local
demo profile.  It seeds a bounded synthetic case through repositories, reads
that case back from PostgreSQL for fresh analysis, and drives policy,
approval, Action Gateway, reconciliation, verification, and audit.  The
canonical replay runner is not used as the authoritative read path.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from action_gateway.reconciliation import reconcile_unknown
from action_gateway.service import ActionGateway, ActionGatewayError
from action_gateway.verification import VerificationService, verify_and_route
from agent.fresh_run import AgentRun
from analysis.deterministic_summary import DeterministicAnalysisResult, run_us2_analysis
from analysis.proposal_validator import (
    AuthoritativeAttribution,
    AuthoritativeResource,
    ProposalValidationContext,
    ProposalValidationResult,
    ProposalValidator,
)
from connectors.actions.manifests import build_action_manifests
from connectors.simulators.actions import ActionSimulatorScenario, DeterministicActionSimulator
from escalation.service import EscalationService
from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayRequest,
)
from packages.contracts.analysis_policy import (
    ActionType,
    Approval,
    ApprovalStatus,
    ModelAnalysisRequest,
    ModelBudget,
    PolicyDecision,
    PolicyResult,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.connectors import ConnectorMode, ConnectorType
from policy.evaluator import evaluate_policy
from policy.versions import (
    PolicyPublicationStatus,
    PolicyScope,
    PolicyVersion,
    build_policy_version,
)
from pydantic import BaseModel, ConfigDict, Field
from timeline.models import TimelineEvent

from app.audit.chain import AuditChain
from app.audit.model_analysis import (
    ModelAnalysisAudit,
    agent_run_to_model_analysis_audit,
)
from app.audit.policy import persist_approval_event, persist_policy_decision
from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext
from app.config import Settings
from app.db.unit_of_work import PostgresUnitOfWork
from cases.terminal_states import CaseTerminalService, transition_case

ConnectionFactory = Callable[[], Any]


class LocalSeedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = Field(default=None, min_length=1)


class LocalExecuteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    scenario: str = Field(
        default=ActionSimulatorScenario.COMPLETED.value,
        pattern="^(accepted|rejected|completed|failed|unknown)$",
    )


class LocalResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escalation_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)


class LocalRuntimeError(RuntimeError):
    """A local application operation could not complete safely."""


class LocalDemoRuntime:
    """Application service for the source-built authoritative local profile."""

    def __init__(
        self,
        settings: Settings,
        *,
        connection_factory: ConnectionFactory | None = None,
        approval_service: Any | None = None,
    ) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or _postgres_connection_factory(settings)
        if approval_service is None:
            from approvals.service import ApprovalService

            approval_service = ApprovalService()
        self.approval_service = approval_service

    def seed_case(self, tenant_id: str, case_id: str | None = None) -> dict[str, Any]:
        """Create the bounded synthetic merchant case in PostgreSQL.

        The fixture is a seed input only.  Every later read and fresh request
        is assembled from rows written by this operation.
        """

        source = _load_seed_fixture()
        requested_case_id = (case_id or f"case-local-demo-{_short_hash(tenant_id)}").strip()
        if not requested_case_id:
            raise ValueError("case_id is required")
        context = _user_context(tenant_id, "local-demo-reviewer", {RequiredRole.REVIEWER.value})
        with self._uow(context) as uow:
            tenant = uow.tenants.get(tenant_id=tenant_id)
            if tenant is None:
                uow.tenants.create(
                    tenant_id=tenant_id,
                    display_name="RECLAIM localhost synthetic merchant",
                )

            incident_id = f"incident:{requested_case_id}"
            correlation_id = f"correlation:{requested_case_id}"
            uow.incidents.create_or_get(
                incident_id=incident_id,
                source="local_synthetic_demo",
                reporter_context={
                    "source": "merchant-controlled deterministic seed",
                    "production_data": False,
                },
                received_at=_utc(source.get("correlation_id") and "2026-09-01T09:00:02Z"),
                correlation_key=correlation_id,
                raw_input_reference="seed:canonical-demo-v1.0.0",
                intake_status="accepted",
                deduplication_identity=f"local-synthetic:{tenant_id}:{requested_case_id}",
            )
            case = uow.cases.get(case_id=requested_case_id)
            if case is None:
                case = uow.cases.create(
                    case_id=requested_case_id,
                    incident_id=incident_id,
                    current_state="intake_received",
                )

            policy = self._ensure_policy(uow, tenant_id, requested_case_id)
            evidence_ids = self._seed_evidence(uow, source, requested_case_id)
            self._seed_timeline(
                uow,
                source,
                tenant_id=tenant_id,
                case_id=requested_case_id,
                evidence_ids=evidence_ids,
            )
            self._ensure_action_connectors(uow, tenant_id)
            current_state = str(case[3])
            if current_state in {"intake_received", "collecting_evidence"}:
                uow.cases.transition_state(case_id=requested_case_id, new_state="timeline_ready")
            audit_id = f"audit:local-seed:{requested_case_id}"
            if uow.audit.checksum_for_audit_id(tenant_id=tenant_id, audit_id=audit_id) is None:
                AuditChain(uow.audit).append(
                    AuditChain(uow.audit).build_record(
                        tenant_id=tenant_id,
                        audit_id=audit_id,
                        case_id=requested_case_id,
                        actor="local-demo-seeder",
                        action="case.synthetic.seeded",
                        input_references=("seed:canonical-demo-v1.0.0",),
                        output_references=(requested_case_id, incident_id),
                        evidence_references=tuple(evidence_ids.values()),
                        policy_version_id=policy.policy_version_id,
                        correlation_ids=(correlation_id,),
                        outcome="timeline_ready",
                        recorded_at=datetime.now(UTC),
                    )
                )
            return {
                "tenant_id": tenant_id,
                "case_id": requested_case_id,
                "incident_id": incident_id,
                "correlation_id": correlation_id,
                "policy_version_id": policy.policy_version_id,
                "state": "timeline_ready"
                if current_state in {"intake_received", "collecting_evidence"}
                else current_state,
                "authoritative": True,
                "source": "postgresql",
                "synthetic": True,
            }

    def request_for_case(
        self, tenant_id: str, case_id: str, budget: ModelBudget
    ) -> ModelAnalysisRequest:
        """Build the fresh request from authoritative PostgreSQL rows."""

        with self._uow(_service_context(tenant_id)) as uow:
            result = self._deterministic_from_uow(uow, tenant_id, case_id)
            request = result.analysis_request
            if request is None:
                raise LookupError("authoritative case did not produce an analysis request")
            representation = dict(request.redacted_case_representation)
            provenance = dict(representation.get("provenance", {}))
            provenance.update(
                {
                    "source": "authoritative-postgresql-case",
                    "production_data": False,
                    "mode": ProviderMode.LIVE.value,
                    "replay_label": ProviderMode.LIVE.value,
                }
            )
            representation["provenance"] = provenance
            return request.model_copy(
                update={
                    "redacted_case_representation": representation,
                    "budget": budget,
                    "provider_mode": ProviderMode.LIVE,
                    "replay_label": ProviderMode.LIVE,
                }
            )

    def persist_agent_run(self, run: AgentRun) -> Mapping[str, Any]:
        """Persist the typed run and advance only the deterministic downstream gates."""

        tenant_id = run.request.tenant_id
        case_id = run.request.case_id
        with self._uow(_service_context(tenant_id)) as uow:
            deterministic = self._deterministic_from_uow(uow, tenant_id, case_id)
            validation_context, resources = self._validation_context(uow, run, deterministic)
            validations: dict[str, ProposalValidationResult] = {}
            if run.analysis_response is not None:
                validator = ProposalValidator()
                for proposal in run.analysis_response.proposals:
                    validations[proposal.proposal_id] = validator.validate(
                        proposal, validation_context
                    )
            audit = agent_run_to_model_analysis_audit(
                run,
                deterministic,
                proposal_validations=validations,
            )
            uow.model_runs.persist(audit)
            model_audit_id = f"audit:model-analysis:{audit.analysis_id}"
            if (
                uow.audit.checksum_for_audit_id(tenant_id=tenant_id, audit_id=model_audit_id)
                is None
            ):
                audit.append_audit_record(
                    AuditChain(uow.audit),
                    audit_id=model_audit_id,
                    actor="fresh-agent-runtime",
                )

            _persist_deterministic_outputs(uow, deterministic, audit.analysis_id)
            current = uow.cases.get(case_id=case_id)
            if current is not None and str(current[3]) in {
                "timeline_ready",
                "analyzed",
            }:
                uow.cases.mark_analyzed(case_id=case_id)

            policy = self._policy_for_case(uow, tenant_id, case_id, run.request.policy_version_id)
            decisions: list[PolicyDecision] = []
            for proposal in run.analysis_response.proposals if run.analysis_response else ():
                validation = validations.get(proposal.proposal_id)
                resource = resources.get(proposal.target_resource)
                if validation is None or validation.status.value != "valid" or resource is None:
                    continue
                existing_proposal = _action_proposal_row(uow, case_id, proposal.proposal_id)
                canonical_id = validation.canonical_action_identity
                if existing_proposal is None:
                    uow.proposals.create(
                        proposal_id=proposal.proposal_id,
                        case_id=case_id,
                        action_type=proposal.action_type.value,
                        target_resource=proposal.target_resource,
                        parameters=_gateway_parameters(proposal),
                        rationale=proposal.rationale,
                        evidence_references=proposal.evidence_references,
                        attribution_references=proposal.attribution_references,
                        requested_amount_minor=proposal.requested_amount_minor,
                        currency=proposal.currency,
                        idempotency_key=canonical_id or proposal.idempotency_key,
                        analysis_id=proposal.analysis_id,
                        status="policy_pending",
                    )
                decision = evaluate_policy(
                    proposal=proposal,
                    policy_version=policy,
                    resource=resource,
                    confidence=_proposal_confidence(deterministic, proposal),
                    amount_minor=proposal.requested_amount_minor or 0,
                    currency=proposal.currency,
                    is_reversible=True,
                    customer_impact={"class": "low"},
                    correlation_id=run.request.correlation_id,
                    evaluated_at=datetime.now(UTC),
                    decision_id=f"decision:{audit.analysis_id}:{proposal.proposal_id}",
                )
                prior = uow.policy_decisions.for_proposal(proposal_id=proposal.proposal_id)
                if prior:
                    decision = _policy_from_row(prior[-1])
                else:
                    persist_policy_decision(decision, unit_of_work=uow)
                uow.connection.execute(
                    """
                    UPDATE public.action_proposals
                    SET policy_decision_id = %s, status = %s
                    WHERE tenant_id = %s AND proposal_id = %s AND case_id = %s
                    """,
                    (
                        decision.decision_id,
                        "approval_pending"
                        if decision.result is PolicyResult.APPROVAL_REQUIRED
                        else decision.result.value,
                        tenant_id,
                        proposal.proposal_id,
                        case_id,
                    ),
                )
                decisions.append(decision)
                if decision.result in {PolicyResult.ALLOW, PolicyResult.APPROVAL_REQUIRED}:
                    uow.cases.mark_action_pending(case_id=case_id)
                    if decision.result is PolicyResult.APPROVAL_REQUIRED:
                        self.approval_service.request_approval(
                            tenant_id=tenant_id,
                            case_id=case_id,
                            proposal_id=proposal.proposal_id,
                            action_type=proposal.action_type.value,
                            target_resource=proposal.target_resource,
                            proposer_id=f"analysis:{audit.analysis_id}",
                            policy_version_id=policy.policy_version_id,
                            correlation_id=run.request.correlation_id,
                            requested_at=datetime.now(UTC),
                            request_id=_approval_request_id(proposal, policy),
                        )

            return {
                "policy_result": decisions[0].model_dump(mode="json") if decisions else None,
                "authoritative_persistence": "postgresql",
                "fresh_run_id": run.run_id,
            }

    def read_agent_run(self, tenant_id: str, case_id: str, run_id: str) -> Mapping[str, Any] | None:
        with self._uow(_service_context(tenant_id)) as uow:
            for row in reversed(uow.model_runs.for_case(case_id=case_id)):
                audit = uow.model_runs.get_audit(analysis_id=str(row[1]))
                if audit is None or audit.provenance.get("agent_run_id") != run_id:
                    continue
                return _agent_payload_from_audit(
                    audit, self.settings.fresh_agent_action_environment, run_id
                )
        return None

    def mode_payload(self) -> dict[str, Any]:
        configured_model = bool(os.getenv("RECLAIM_SPECIALIST_MODEL", "").strip())
        return {
            "requested_mode": "live",
            "effective_mode": "live",
            "final_mode": "live",
            "provider_available": configured_model,
            "connector_available": True,
            "provider_qualified": configured_model,
            "connector_qualified": True,
            "live_execution_occurred": False,
            "live_actions_enabled": False,
            "live_financial_actions_enabled": False,
            "availability_reasons": []
            if configured_model
            else [
                "fresh provider is not configured; the next fresh run will be explicit "
                "MODEL_UNAVAILABLE"
            ],
            "fallback_reason": None
            if configured_model
            else "MODEL_UNAVAILABLE: configure RECLAIM_SPECIALIST_MODEL and the LiteLLM endpoint",
            "label": "fresh_agent",
            "simulation_notice": (
                "Fresh Agent analysis + Action Gateway Simulator/Test Mode. "
                "No live merchant effects."
            ),
            "decision_version": "local-authoritative-demo-v1.0.0",
            "execution_mode": "fresh_agent",
            "action_environment": self.settings.fresh_agent_action_environment,
            "authoritative": True,
        }

    def readiness(self) -> None:
        """Open and close a tenant-scoped transaction to verify PostgreSQL access."""

        with self._uow(_service_context(self.settings.tenant_id)):
            return None

    def operator_view(self, tenant_id: str, case_id: str) -> dict[str, Any]:
        with self._uow(_service_context(tenant_id)) as uow:
            case = uow.cases.get(case_id=case_id)
            if case is None:
                raise LookupError("authoritative case was not found")
            incident = uow.incidents.get(incident_id=str(case[2]))
            tenant = uow.tenants.get(tenant_id=tenant_id)
            orchestration = uow.orchestration.latest_for_case(case_id=case_id)
            timeline_rows = uow.timeline.for_case(case_id=case_id)
            attribution_rows = uow.attributions.for_case(case_id=case_id)
            attribution_by_event: dict[str, object] = {}
            for row in attribution_rows:
                attribution_by_event[str(row[2])] = row
            latest_audit = _latest_model_audit(uow, case_id)
            proposal_record = _latest_proposal(latest_audit)
            proposal = _proposal_payload(
                proposal_record,
                resources=self._resources_from_timeline(tenant_id, case_id, timeline_rows),
            )
            policy_decision = None
            approval = None
            action = None
            verification = None
            escalation = None
            if proposal is not None:
                policy_rows = uow.policy_decisions.for_proposal(proposal_id=proposal["proposal_id"])
                if policy_rows:
                    policy_decision = _policy_payload(_policy_from_row(policy_rows[-1]))
                    approval = _approval_payload(
                        uow,
                        tenant_id,
                        case_id,
                        proposal,
                        policy_decision,
                        latest_audit,
                    )
                canonical = proposal.get("canonical_action_id")
                if canonical:
                    execution = uow.actions.get_by_canonical(canonical_action_id=canonical)
                    if execution is not None:
                        action = _execution_payload(execution)
                        verification_rows = uow.verifications.for_execution(
                            execution_id=str(execution.execution_id)
                        )
                        if verification_rows:
                            verification = _verification_payload(verification_rows[-1])
            escalation_rows = uow.escalations.for_case(case_id=case_id)
            if escalation_rows:
                escalation = _escalation_payload(escalation_rows[-1])
            exposure = _exposure_payload(uow.exposures.for_case(case_id=case_id))
            audit = [_audit_payload(row) for row in uow.audit.for_case(case_id=case_id)]
            refreshed = _iso(case[7] or case[6])
            return {
                "case": {
                    "case_id": case_id,
                    "tenant_id": tenant_id,
                    "incident_id": str(case[2]),
                    "merchant_name": str(tenant[1]) if tenant is not None else tenant_id,
                    "state": str(case[3]),
                    "owner_id": str(case[4]) if case[4] else "merchant-ops-local",
                    "severity": None,
                    "last_refreshed_at": refreshed,
                },
                "reported_incident": _reported_incident_payload(incident),
                "orchestration": _orchestration_payload(orchestration),
                "agent_analysis": _agent_analysis_payload(latest_audit),
                "timeline": [
                    _timeline_payload(row, attribution_by_event.get(str(row[1])))
                    for row in timeline_rows
                ],
                "exposure": exposure,
                "proposal": proposal,
                "policy_decision": policy_decision,
                "approval": approval,
                "action": action,
                "verification": verification,
                "escalation": escalation,
                "audit": audit,
                "mode": self.mode_payload(),
                "evaluation": {
                    "label": "authoritative synthetic demo",
                    "fixture_version": "seeded-once-canonical-v1.0.0",
                    "dataset_version": "local-synthetic-v1.0.0",
                    "provenance": {
                        "production_data": False,
                        "source": "PostgreSQL authoritative synthetic case",
                    },
                    "confidence_interval_metadata": {},
                },
                "next_human_decision": _next_decision(str(case[3]), approval, action, verification),
                "data_as_of": refreshed,
                "read_only": False,
                "authoritative": True,
                "remote_side_effects": [],
            }

    def persist_approval_decision(self, approval: Approval) -> None:
        with self._uow(_service_context(approval.tenant_id)) as uow:
            persist_approval_event(approval, unit_of_work=uow, actor=approval.approver_id)
            uow.connection.execute(
                """
                UPDATE public.action_proposals
                SET status = %s
                WHERE tenant_id = %s AND case_id = %s AND proposal_id = %s
                """,
                (
                    "approved" if approval.status is ApprovalStatus.APPROVED else "rejected",
                    approval.tenant_id,
                    approval.case_id,
                    approval.proposal_id,
                ),
            )
            if approval.status is ApprovalStatus.APPROVED:
                current = uow.cases.get(case_id=approval.case_id)
                if current is not None and str(current[3]) == "analyzed":
                    uow.cases.mark_action_pending(case_id=approval.case_id)

    def ensure_approval_request(self, tenant_id: str, case_id: str, proposal_id: str) -> Any:
        with self._uow(_service_context(tenant_id)) as uow:
            row = _action_proposal_row(uow, case_id, proposal_id)
            if row is None:
                raise LookupError("proposal is not present in this case")
            policy_rows = uow.policy_decisions.for_proposal(proposal_id=proposal_id)
            if not policy_rows:
                raise LookupError("policy decision is not present for this proposal")
            policy = self._policy_for_case(uow, tenant_id, case_id, str(policy_rows[-1][4]))
            proposal = _typed_proposal_from_row(row, _case_correlation(uow, case_id))
            request_id = _approval_request_id(proposal, policy)
            existing = getattr(self.approval_service, "_requests", {}).get((tenant_id, request_id))
            if existing is not None:
                return existing
            return self.approval_service.request_approval(
                tenant_id=tenant_id,
                case_id=case_id,
                proposal_id=proposal_id,
                action_type=proposal.action_type.value,
                target_resource=proposal.target_resource,
                proposer_id=f"analysis:{proposal.analysis_id}",
                policy_version_id=policy.policy_version_id,
                correlation_id=_case_correlation(uow, case_id),
                requested_at=datetime.now(UTC),
                request_id=request_id,
            )

    def restore_approval_request(self, tenant_id: str, request_id: str) -> Any:
        """Rehydrate the in-memory approval service from authoritative rows."""

        if not request_id.startswith("approval-request:"):
            raise LookupError("approval request id is not a local demo request")
        with self._uow(_service_context(tenant_id)) as uow:
            rows = uow.connection.execute(
                """
                SELECT case_id, proposal_id
                FROM public.action_proposals
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
            match: tuple[str, str] | None = None
            for row in rows:
                proposal_id = str(row[1])
                policy_rows = uow.policy_decisions.for_proposal(proposal_id=proposal_id)
                if not policy_rows:
                    continue
                policy_version_id = str(policy_rows[-1][4])
                if request_id == f"approval-request:{proposal_id}:{policy_version_id}":
                    match = (str(row[0]), proposal_id)
                    break
        if match is None:
            raise LookupError("approval request is not present in the authoritative case")
        return self.ensure_approval_request(tenant_id, match[0], match[1])

    def execute_approved_action(
        self,
        tenant_id: str,
        case_id: str,
        proposal_id: str,
        *,
        scenario: ActionSimulatorScenario | str = ActionSimulatorScenario.COMPLETED,
    ) -> dict[str, Any]:
        with self._uow(
            _user_context(tenant_id, "local-demo-reviewer", {RequiredRole.REVIEWER.value})
        ) as uow:
            proposal_row = _action_proposal_row(uow, case_id, proposal_id)
            if proposal_row is None:
                raise LookupError("proposal is not present in this case")
            proposal = _typed_proposal_from_row(proposal_row, _case_correlation(uow, case_id))
            policy_rows = uow.policy_decisions.for_proposal(proposal_id=proposal_id)
            if not policy_rows:
                raise LocalRuntimeError("policy decision is not present for this proposal")
            decision = _policy_from_row(policy_rows[-1])
            approval = _approval_for_proposal(uow, tenant_id, proposal_id)
            if decision.result is PolicyResult.APPROVAL_REQUIRED and approval is None:
                raise LocalRuntimeError(
                    "independent approval is required before gateway submission"
                )
            if (
                decision.result is not PolicyResult.ALLOW
                and decision.result is not PolicyResult.APPROVAL_REQUIRED
            ):
                raise LocalRuntimeError("policy decision does not authorize gateway submission")
            resource = self._resources_from_timeline(
                tenant_id, case_id, uow.timeline.for_case(case_id=case_id)
            ).get(proposal.target_resource)
            if resource is None:
                raise LocalRuntimeError("authoritative action resource is missing")
            canonical = str(proposal_row[11])
            existing = uow.actions.get_by_canonical(canonical_action_id=canonical)
            if existing is not None and existing.status in {
                ActionExecutionState.VERIFIED_SUCCESS,
                ActionExecutionState.VERIFIED_FAILURE,
                ActionExecutionState.ESCALATED,
            }:
                return _execution_payload(existing)

            request = _gateway_request(proposal, decision, approval, canonical)
            simulator = DeterministicActionSimulator.for_operation(
                tenant_id,
                proposal.action_type.value,
                scenario=scenario,
                resource_states={proposal.target_resource: resource.state},
            )
            gateway = ActionGateway(
                connectors={simulator.manifest.connector_id: simulator},
                execution_store=uow.actions,
            )
            service_context = _action_gateway_context(tenant_id)
            try:
                response = gateway.submit(
                    request,
                    policy_decision=decision,
                    approval=approval,
                    authoritative_resource=resource,
                    authorization_context=service_context,
                    canonical_action_id=canonical,
                )
            except ActionGatewayError:
                raise
            execution = uow.actions.get(execution_id=response.execution_id)
            if execution is None:
                raise LocalRuntimeError("gateway execution did not persist")
            persist_action = _action_audit
            persist_action(
                uow,
                tenant_id=tenant_id,
                case_id=case_id,
                proposal=proposal,
                response=response,
                approval=approval,
            )
            if response.state is ActionExecutionState.UNKNOWN:
                reconciled = reconcile_unknown(
                    record=execution,
                    remote=_DatabaseSafeSimulator(simulator),
                    store=uow.actions,
                )
                execution = reconciled.record or uow.actions.get(execution_id=response.execution_id)
                _action_audit(
                    uow,
                    tenant_id=tenant_id,
                    case_id=case_id,
                    proposal=proposal,
                    response=response,
                    approval=approval,
                    outcome="reconciled"
                    if reconciled.effect_occurred is not None
                    else "reconciliation_unresolved",
                )
            uow.cases.mark_containing(case_id=case_id)
            if execution is None:
                raise LocalRuntimeError("execution disappeared during reconciliation")
            verification = VerificationService(
                verifier=_LocalMerchantStateVerifier(simulator),
                repository=uow.verifications,
            ).verify(
                request=request,
                execution=execution,
                evidence_references=tuple(proposal.evidence_references),
            )
            if verification.terminal_state is not None:
                if verification.terminal_state == "verified_contained":
                    uow.actions.mark_verified(
                        execution_id=execution.execution_id,
                        success=True,
                        result_reference=f"verification:{verification.verification.verification_id}",
                    )
                elif verification.terminal_state == "verified_failed":
                    uow.actions.mark_verified(
                        execution_id=execution.execution_id,
                        success=False,
                        result_reference=f"verification:{verification.verification.verification_id}",
                    )
                transition = transition_case(
                    current_state="containing",
                    requested_state=verification.terminal_state,
                    tenant_id=tenant_id,
                    case_id=case_id,
                    action_id=canonical,
                    execution_id=execution.execution_id,
                    verification_id=verification.verification.verification_id,
                    verification_result=verification.verification.result.value,
                    required_actions_completed=verification.terminal_state == "verified_contained",
                    unresolved=False,
                    remaining_exposure_minor=0,
                    currency="INR",
                    correlation_ids=(request.correlation_id,),
                )
                CaseTerminalService(unit_of_work=uow).transition(transition)
            else:
                routed = verify_and_route(
                    verification=verification.verification,
                    escalation_owner="local-demo-escalation-owner",
                    remaining_exposure_minor=0,
                    currency="INR",
                    evidence_references=tuple(proposal.evidence_references),
                    recommended_human_decision="review merchant state and decide containment",
                    case_id=case_id,
                    canonical_action_id=canonical,
                    policy_version_id=decision.policy_version_id,
                    escalation_service=EscalationService(repository=uow.escalations),
                    owner_tenant_id=tenant_id,
                )
                if routed.escalation is None:
                    raise LocalRuntimeError("inconclusive verification did not create escalation")
                uow.actions.mark_escalated(
                    execution_id=execution.execution_id,
                    result_reference=f"escalation:{routed.escalation.escalation_id}",
                )
                transition = transition_case(
                    current_state="containing",
                    requested_state="escalated_unresolved",
                    tenant_id=tenant_id,
                    case_id=case_id,
                    action_id=canonical,
                    execution_id=execution.execution_id,
                    verification_id=verification.verification.verification_id,
                    escalation_id=routed.escalation.escalation_id,
                    verification_result=verification.verification.result.value,
                    unresolved=True,
                    remaining_exposure_minor=0,
                    currency="INR",
                    correlation_ids=(request.correlation_id,),
                )
                CaseTerminalService(unit_of_work=uow).transition(
                    transition, owner="local-demo-escalation-owner"
                )
            return {
                **_execution_payload(
                    uow.actions.get(execution_id=execution.execution_id) or execution
                ),
                "verification": verification.verification.model_dump(mode="json"),
                "terminal_state": verification.terminal_state or "escalated_unresolved",
                "reconciliation_required": response.reconciliation_required,
                "simulation": True,
                "remote_side_effects": [],
            }

    def resolve_escalation(self, tenant_id: str, escalation_id: str, expected_version: int) -> Any:
        with self._uow(
            _user_context(
                tenant_id, "local-demo-escalation-owner", {RequiredRole.ESCALATION_OWNER.value}
            )
        ) as uow:
            row = uow.escalations.resolve(
                escalation_id=escalation_id, expected_version=expected_version
            )
            _action_audit(
                uow,
                tenant_id=tenant_id,
                case_id=str(row[2]),
                proposal=None,
                response=None,
                approval=None,
                outcome="escalation_resolved",
                escalation_id=escalation_id,
            )
            return _escalation_payload(row)

    def _uow(self, context: TenantAuthorizationContext) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(
            self._connection_factory,
            authorization_context=context,
        )

    def unit_of_work_factory(self, context: TenantAuthorizationContext) -> PostgresUnitOfWork:
        """Expose the same explicit UoW boundary to API application services."""

        return self._uow(context)

    def _deterministic_from_uow(
        self, uow: PostgresUnitOfWork, tenant_id: str, case_id: str
    ) -> DeterministicAnalysisResult:
        case = uow.cases.get(case_id=case_id)
        if case is None:
            raise LookupError("authoritative case was not found")
        incident = uow.incidents.get(incident_id=str(case[2]))
        correlation_id = (
            str(incident[5]) if incident is not None else _case_correlation(uow, case_id)
        )
        timeline = tuple(_timeline_from_row(row) for row in uow.timeline.for_case(case_id=case_id))
        if not timeline:
            raise LookupError("authoritative case has no timeline")
        evidence = tuple(
            _evidence_payload_row(row) for row in uow.evidence.for_case(case_id=case_id)
        )
        policy_id = self._policy_id(uow, tenant_id)
        uncertainty = uow.cases.timeline_uncertainty(case_id=case_id) or ()
        return run_us2_analysis(
            tenant_id=tenant_id,
            case_id=case_id,
            correlation_id=correlation_id,
            evidence_items=evidence,
            timeline_events=timeline,
            timeline_uncertainty=uncertainty,
            policy_version_id=policy_id,
            provider_mode=ProviderMode.REPLAY,
            deterministic_seed="local-synthetic-seed-v1",
        )

    def _validation_context(
        self,
        uow: PostgresUnitOfWork,
        run: AgentRun,
        deterministic: DeterministicAnalysisResult,
    ) -> tuple[ProposalValidationContext, dict[str, AuthoritativeResource]]:
        timeline_rows = uow.timeline.for_case(case_id=run.request.case_id)
        events = tuple(_timeline_from_row(row) for row in timeline_rows)
        evidence = tuple(
            _evidence_payload_row(row) for row in uow.evidence.for_case(case_id=run.request.case_id)
        )
        resources = self._resources_from_timeline(
            run.request.tenant_id, run.request.case_id, timeline_rows
        )
        attributions = tuple(
            AuthoritativeAttribution(
                timeline_event_id=item.timeline_event_id,
                label=item.label,
                confidence=item.confidence,
                tenant_id=run.request.tenant_id,
                case_id=run.request.case_id,
                evidence_references=item.evidence_references,
                rationale=item.rationale,
                method=item.method,
                model_or_rules_version=item.model_or_rules_version,
            )
            for item in deterministic.attributions
        )
        result = deterministic
        if run.analysis_response is not None:
            from dataclasses import replace

            result = replace(
                deterministic,
                mode="live",
                analysis_request=run.request,
                analysis_response=run.analysis_response,
            )
        context = ProposalValidationContext.from_analysis_result(
            result,
            connectors=build_action_manifests(run.request.tenant_id),
            action_connector_ids={
                ActionType.REVOKE_SUSPICIOUS_SESSION.value: "session-actions",
                ActionType.HOLD_FULFILLMENT.value: "fulfillment-actions",
            },
            resources=resources,
            evidence_references=tuple(str(item["evidence_id"]) for item in evidence),
            evidence_items=evidence,
            timeline_events=events,
            attributions=attributions,
            response_checksum=run.response_checksum,
        )
        return context, resources

    def _ensure_policy(
        self, uow: PostgresUnitOfWork, tenant_id: str, case_id: str
    ) -> PolicyVersion:
        policy_id = self._policy_id(uow, tenant_id)
        existing = uow.policy_versions.get(policy_version_id=policy_id)
        if existing is not None:
            return _policy_version_from_row(existing)
        draft = build_policy_version(
            policy_version_id=policy_id,
            tenant_id=tenant_id,
            scope_type=PolicyScope.TENANT,
            thresholds={
                "min_confidence": 0.85,
                "max_amount_minor": 0,
                "allowed_customer_impact_classes": ["low"],
                "allowed_resource_states": {
                    "revoke_suspicious_session": ["active"],
                    "hold_fulfillment": ["ready", "authorized", "unfulfilled", "pending"],
                },
            },
            action_allowlist=[
                ActionType.REVOKE_SUSPICIOUS_SESSION.value,
                ActionType.HOLD_FULFILLMENT.value,
            ],
            approval_rules={
                ActionType.REVOKE_SUSPICIOUS_SESSION.value: "required",
                ActionType.HOLD_FULFILLMENT.value: "required",
            },
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            effective_to=None,
            author="local-demo-policy-owner",
            publication_status=PolicyPublicationStatus.DRAFT,
        )
        uow.policy_versions.create(
            policy_version_id=draft.policy_version_id,
            scope_type=draft.scope_type.value,
            thresholds=draft.payload()["thresholds"],
            action_allowlist=tuple(draft.action_allowlist),
            approval_rules=draft.payload()["approval_rules"],
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            author=draft.author,
            publication_status=draft.publication_status.value,
            immutable_checksum=draft.immutable_checksum,
        )
        uow.policy_versions.publish(
            policy_version_id=policy_id,
            actor="local-demo-policy-owner",
            authorization_context=_user_context(
                tenant_id, "local-demo-policy-owner", {RequiredRole.POLICY_OWNER.value}
            ),
        )
        return draft.with_publication_status(PolicyPublicationStatus.PUBLISHED)

    @staticmethod
    def _policy_id(uow: PostgresUnitOfWork, tenant_id: str) -> str:
        del uow
        return f"policy:local-demo:{tenant_id}"

    def _policy_for_case(
        self, uow: PostgresUnitOfWork, tenant_id: str, case_id: str, policy_id: str
    ) -> PolicyVersion:
        row = uow.policy_versions.get(policy_version_id=policy_id)
        if row is None:
            raise LocalRuntimeError("authoritative policy version is missing")
        return _policy_version_from_row(row)

    @staticmethod
    def _seed_evidence(
        uow: PostgresUnitOfWork, source: Mapping[str, Any], case_id: str
    ) -> dict[str, str]:
        identifiers: dict[str, str] = {}
        for item in source.get("evidence", ()):
            original = str(item["evidence_id"])
            scoped = f"{original}:{case_id}"
            identifiers[original] = scoped
            uow.evidence.create_or_get(
                evidence_id=scoped,
                case_id=case_id,
                connector_id=str(item["connector_id"]),
                resource_type=str(item.get("source_identity", "merchant_evidence")),
                # The same deterministic fixture can seed multiple local cases.
                # Scope the provider identity so the tenant-level evidence
                # uniqueness constraint does not make the recovery button fail
                # with a duplicate fixture row for a new case.
                source_identifier=(
                    f"{item.get('provider_identifier', original)}:{case_id}"
                ),
                observed_at=None,
                received_at=datetime(2026, 9, 1, 9, 0, 2, tzinfo=UTC),
                raw_object_uri=None,
                checksum=str(item.get("raw_checksum", "")),
                normalization_status="normalized",
                completeness=str(item.get("completeness", "complete")),
                trust_classification="untrusted",
                collection_error=None,
            )
        return identifiers

    @staticmethod
    def _seed_timeline(
        uow: PostgresUnitOfWork,
        source: Mapping[str, Any],
        *,
        tenant_id: str,
        case_id: str,
        evidence_ids: Mapping[str, str],
    ) -> None:
        session_id = f"session:{case_id}"
        fulfillment_id = f"fulfillment:{case_id}"
        order_id = f"order:{case_id}"
        events = list(source.get("timeline_events", ()))
        events.append(
            {
                "timeline_event_id": "timeline-profile-local",
                "canonical_event_type": "profile.changed",
                "source_event_ids": ["profile-local-001"],
                "source_identity": "profile-simulator",
                "effective_at": "2026-09-01T08:59:00Z",
                "observed_at": "2026-09-01T08:59:01Z",
                "received_at": "2026-09-01T08:59:02Z",
                "ordering_key": "2026-09-01T08:59:00Z|profile.changed|profile-local-001",
                "dedupe_key": "profile:local",
                "evidence_references": ["evidence-partial-001"],
                "uncertainty_reasons": [],
                "event_payload": {
                    "profile_change_id": f"profile-change:{case_id}",
                    "changed_by": "unknown_actor",
                    "change_type": "email",
                },
            }
        )
        for item in events:
            original_id = str(item["timeline_event_id"])
            event_id = f"{original_id}:{case_id}"
            payload = dict(item.get("event_payload", {}))
            if str(item.get("canonical_event_type")) == "session.opened":
                payload.update(
                    {
                        "session_id": session_id,
                        "fulfillment_id": fulfillment_id,
                        "order_id": order_id,
                    }
                )
            for key in ("payment_id", "profile_change_id"):
                if key in payload:
                    payload[key] = f"{payload[key]}:{case_id}"
            payload["_reclaim_provenance"] = {
                "source_identity": str(item.get("source_identity", "synthetic-source")),
                "source_event_id": str((item.get("source_event_ids") or [event_id])[0]),
                "observed_at": str(item.get("observed_at", item.get("effective_at"))),
                "received_at": str(item.get("received_at", item.get("effective_at"))),
            }
            refs = tuple(
                evidence_ids.get(str(ref), str(ref)) for ref in item.get("evidence_references", ())
            )
            uow.timeline.upsert(
                timeline_event_id=event_id,
                case_id=case_id,
                canonical_event_type=str(item["canonical_event_type"]),
                source_event_ids=tuple(str(value) for value in item.get("source_event_ids", ())),
                effective_at=_utc(str(item["effective_at"])),
                ordering_key=str(item["ordering_key"]).replace(
                    str(item["timeline_event_id"]), original_id
                ),
                dedupe_key=f"{item['dedupe_key']}:{case_id}",
                event_payload=payload,
                evidence_references=refs,
                conflicting_source_event_ids=tuple(item.get("conflicting_source_event_ids", ())),
                uncertainty_reasons=tuple(item.get("uncertainty_reasons", ())),
            )

    @staticmethod
    def _ensure_action_connectors(uow: PostgresUnitOfWork, tenant_id: str) -> None:
        manifests = build_action_manifests(tenant_id)
        for manifest in manifests.values():
            existing = uow.connection.execute(
                "SELECT connector_id FROM public.connector_configurations "
                "WHERE tenant_id = %s AND connector_id = %s",
                (tenant_id, manifest.connector_id),
            ).fetchone()
            if existing is None:
                uow.connectors.create(
                    connector_id=manifest.connector_id,
                    contract_version=manifest.contract_version,
                    connector_type=ConnectorType.ACTION.value,
                    allowed_resources=manifest.resources,
                    allowed_operations=manifest.operations,
                    auth_scope=manifest.auth_scope,
                    credential_scope_ref=f"local-demo:{manifest.connector_id}",
                    schema_version=manifest.request_schema,
                    failure_state_version="connector-failure-v1.0.0",
                    mode=ConnectorMode.SIMULATOR.value,
                )

    def _resources_from_timeline(
        self, tenant_id: str, case_id: str, rows: list[object]
    ) -> dict[str, AuthoritativeResource]:
        resources: dict[str, AuthoritativeResource] = {}
        for row in rows:
            event = _timeline_from_row(row)
            payload = event.event_payload
            if event.canonical_event_type == "session.opened":
                session_id = str(payload.get("session_id", f"session:{case_id}"))
                resources[session_id] = AuthoritativeResource(
                    resource_id=session_id,
                    resource_type="sessions",
                    tenant_id=tenant_id,
                    case_id=case_id,
                    state=str(payload.get("state", "active")),
                    connector_id="session-actions",
                    evidence_references=event.evidence_references,
                    timeline_event_ids=(event.timeline_event_id,),
                    attributes={"implicated": True, "is_reversible": True},
                )
                fulfillment_id = payload.get("fulfillment_id")
                if isinstance(fulfillment_id, str) and fulfillment_id.strip():
                    resources[fulfillment_id] = AuthoritativeResource(
                        resource_id=fulfillment_id,
                        resource_type="fulfillment",
                        tenant_id=tenant_id,
                        case_id=case_id,
                        state="ready",
                        connector_id="fulfillment-actions",
                        evidence_references=event.evidence_references,
                        timeline_event_ids=(event.timeline_event_id,),
                        attributes={"implicated": True, "is_reversible": True},
                    )
        return resources


class _LocalMerchantStateVerifier:
    def __init__(self, simulator: DeterministicActionSimulator) -> None:
        self.simulator = simulator

    def observe(self, request: ActionGatewayRequest) -> Mapping[str, Any]:
        if self.simulator.scenario is ActionSimulatorScenario.COMPLETED:
            return {
                "state": "revoked"
                if request.operation == ActionType.REVOKE_SUSPICIOUS_SESSION.value
                else "held",
                "source": "local-simulator-state-read",
                "tenant_id": request.tenant_id,
                "case_id": request.case_id,
                "connector_id": request.connector_id,
                "target_resource": request.target_resource,
                "contained": True,
            }
        return {
            "state": "unknown",
            "verification": "inconclusive",
            "source": "local-simulator-state-read",
            "tenant_id": request.tenant_id,
            "case_id": request.case_id,
            "connector_id": request.connector_id,
            "target_resource": request.target_resource,
        }


class _DatabaseSafeSimulator:
    """Normalize simulator-only absence labels to the persisted action contract."""

    def __init__(self, simulator: DeterministicActionSimulator) -> None:
        self.simulator = simulator

    def reconcile(self, idempotency_key: str) -> str:
        value = self.simulator.reconcile(idempotency_key)
        return "failed" if value in {"not_submitted", "not_found", "absent"} else value


def create_local_runtime_router(*, runtime: LocalDemoRuntime, verifier: Any) -> Any:
    """Mount typed synthetic-case, operator-view, execution, and escalation routes."""

    from fastapi import APIRouter, Header, HTTPException

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/demo/cases")
    def seed(
        tenant_id: str,
        body: LocalSeedBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _local_authorize(verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return runtime.seed_case(tenant_id, body.case_id)
        except (ValueError, LocalRuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/tenants/{tenant_id}/cases/{case_id}/operator-view")
    def view(
        tenant_id: str,
        case_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _local_authorize(verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return runtime.operator_view(tenant_id, case_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/cases/{case_id}/actions/execute-approved")
    def execute(
        tenant_id: str,
        case_id: str,
        body: LocalExecuteBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _local_authorize(verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return runtime.execute_approved_action(
                tenant_id, case_id, body.proposal_id, scenario=body.scenario
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, LocalRuntimeError, ActionGatewayError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/escalations/resolve")
    def resolve(
        tenant_id: str,
        body: LocalResolveBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        _local_authorize(verifier, authorization, tenant_id, RequiredRole.ESCALATION_OWNER)
        try:
            return runtime.resolve_escalation(tenant_id, body.escalation_id, body.expected_version)
        except (ValueError, LocalRuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _persist_deterministic_outputs(
    uow: PostgresUnitOfWork, result: DeterministicAnalysisResult, analysis_id: str
) -> None:
    for item in result.attributions:
        attribution_id = f"attribution:{analysis_id}:{item.timeline_event_id}:{item.method}"
        exists = uow.attributions.for_timeline_event(timeline_event_id=item.timeline_event_id)
        if not any(str(row[1]) == attribution_id for row in exists):
            uow.attributions.create_suggestion(
                attribution_id=attribution_id,
                suggestion=item,
            )
    if not uow.exposures.for_case(case_id=result.case_id):
        uow.exposures.create_result(exposure_id=f"exposure:{analysis_id}", exposure=result.exposure)


def _action_audit(
    uow: PostgresUnitOfWork,
    *,
    tenant_id: str,
    case_id: str,
    proposal: TypedActionProposal | None,
    response: Any,
    approval: Approval | None,
    outcome: str | None = None,
    escalation_id: str | None = None,
) -> None:
    from app.audit.actions import persist_action_audit

    persist_action_audit(
        tenant_id=tenant_id,
        case_id=case_id,
        action_id=None if proposal is None else proposal.idempotency_key,
        execution_id=None if response is None else response.execution_id,
        escalation_id=escalation_id,
        policy_version_id=None if proposal is None else None,
        approval_id=None if approval is None else approval.approval_id,
        evidence_references=() if proposal is None else proposal.evidence_references,
        correlation_ids=() if proposal is None else (proposal.correlation_id,),
        outcome=outcome or (response.state.value if response is not None else "action"),
        unit_of_work=uow,
    )


def _gateway_request(
    proposal: TypedActionProposal,
    decision: PolicyDecision,
    approval: Approval | None,
    canonical: str,
) -> ActionGatewayRequest:
    payload = {
        "tenant_id": proposal.tenant_id,
        "correlation_id": proposal.correlation_id,
        "case_id": proposal.case_id,
        "proposal_id": proposal.proposal_id,
        "action_type": proposal.action_type.value,
        "connector_id": "session-actions"
        if proposal.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
        else "fulfillment-actions",
        "target_resource": proposal.target_resource,
        "parameters": _gateway_parameters(proposal),
        "policy_decision_id": decision.decision_id,
        "policy_version_id": decision.policy_version_id,
        "approval_id": None if approval is None else approval.approval_id,
        "idempotency_key": canonical,
        "causation_id": proposal.proposal_id,
        "requested_at": datetime.now(UTC),
    }
    payload["operation"] = proposal.action_type.value
    payload["request_checksum"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    return ActionGatewayRequest.model_validate(payload)


def _gateway_parameters(proposal: TypedActionProposal) -> dict[str, str]:
    values = dict(proposal.parameters)
    reason = values.get("reason") or values.get("hold_reason") or values.get("review_reason")
    result: dict[str, str] = {"reason": str(reason or proposal.rationale)}
    if proposal.action_type is ActionType.HOLD_FULFILLMENT:
        result["hold_code"] = "fraud_review"
    return result


def _approval_request_id(proposal: TypedActionProposal, policy: PolicyVersion) -> str:
    return f"approval-request:{proposal.proposal_id}:{policy.policy_version_id}"


def _approval_for_proposal(
    uow: PostgresUnitOfWork, tenant_id: str, proposal_id: str
) -> Approval | None:
    row = uow.connection.execute(
        """
        SELECT tenant_id, approval_id, correlation_id, case_id, proposal_id, approver_id,
               approver_role, proposer_id, scope, policy_version_id, status, approved_at,
               expires_at, separation_of_duties_evidence, version, updated_at
        FROM public.approvals
        WHERE tenant_id = %s AND proposal_id = %s
        ORDER BY approved_at DESC, approval_id DESC LIMIT 1
        """,
        (tenant_id, proposal_id),
    ).fetchone()
    if row is None:
        return None
    return _approval_from_row(row)


def _approval_from_row(row: Any) -> Approval:
    return Approval(
        tenant_id=str(row[0]),
        approval_id=str(row[1]),
        correlation_id=str(row[2]),
        case_id=str(row[3]),
        proposal_id=str(row[4]),
        approver_id=str(row[5]),
        approver_role=str(row[6]),
        proposer_id=str(row[7]),
        scope=str(row[8]),
        policy_version_id=str(row[9]),
        status=ApprovalStatus(str(row[10])),
        approved_at=_as_datetime(row[11]),
        expires_at=None if row[12] is None else _as_datetime(row[12]),
        separation_of_duties_evidence=str(row[13]),
    )


def _policy_version_from_row(row: Any) -> PolicyVersion:
    return PolicyVersion(
        policy_version_id=str(row[0]),
        tenant_id=None if row[1] is None else str(row[1]),
        scope_type=PolicyScope(str(row[2])),
        thresholds=_json_value(row[3]),
        action_allowlist=frozenset(_json_value(row[4]) or ()),
        approval_rules=_json_value(row[5]),
        effective_from=_as_datetime(row[6]),
        effective_to=None if row[7] is None else _as_datetime(row[7]),
        author=str(row[8]),
        publication_status=PolicyPublicationStatus(str(row[9])),
        immutable_checksum=str(row[10]),
    )


def _policy_from_row(row: Any) -> PolicyDecision:
    conditions = _json_value(row[8])
    if not isinstance(conditions, Mapping):
        conditions = {}
    return PolicyDecision(
        tenant_id=str(row[0]),
        correlation_id=str(
            conditions.get("provenance", {}).get("correlation_id", f"case:{row[2]}")
        ),
        decision_id=str(row[1]),
        case_id=str(row[2]),
        proposal_id=str(row[3]),
        policy_version_id=str(row[4]),
        result=PolicyResult(str(row[7])),
        evaluated_conditions=conditions,
        evaluator_version=str(row[9]),
        decided_at=_as_datetime(row[10]),
    )


def _typed_proposal_from_row(row: Any, correlation_id: str) -> TypedActionProposal:
    return TypedActionProposal(
        tenant_id=str(row[0]),
        correlation_id=correlation_id,
        proposal_id=str(row[1]),
        case_id=str(row[2]),
        action_type=ActionType(str(row[3])),
        target_resource=str(row[4]),
        parameters=_json_value(row[5]),
        rationale=str(row[6]),
        evidence_references=tuple(_json_value(row[7]) or ()),
        attribution_references=tuple(_json_value(row[8]) or ()),
        requested_amount_minor=row[9],
        currency=None if row[10] is None else str(row[10]),
        idempotency_key=str(row[11]),
        analysis_id=str(row[12]),
    )


def _action_proposal_row(uow: PostgresUnitOfWork, case_id: str, proposal_id: str) -> Any:
    return uow.connection.execute(
        """
        SELECT tenant_id, proposal_id, case_id, action_type, target_resource, parameters,
               rationale, evidence_references, attribution_references,
               requested_amount_minor, currency, idempotency_key, analysis_id, status
        FROM public.action_proposals
        WHERE tenant_id = %s AND case_id = %s AND proposal_id = %s
        """,
        (uow.tenant_context.tenant_id, case_id, proposal_id),
    ).fetchone()


def _case_correlation(uow: PostgresUnitOfWork, case_id: str) -> str:
    case = uow.cases.get(case_id=case_id)
    if case is None:
        return f"case:{case_id}"
    incident = uow.incidents.get(incident_id=str(case[2]))
    return str(incident[5]) if incident is not None else f"case:{case_id}"


def _latest_model_audit(uow: PostgresUnitOfWork, case_id: str) -> ModelAnalysisAudit | None:
    rows = uow.model_runs.for_case(case_id=case_id)
    for row in reversed(rows):
        audit = uow.model_runs.get_audit(analysis_id=str(row[1]))
        if audit is not None:
            return audit
    return None


def _latest_proposal(audit: ModelAnalysisAudit | None) -> Any | None:
    if audit is None:
        return None
    valid = [item for item in audit.proposals if item.validation_status == "valid"]
    return valid[0] if valid else None


def _proposal_payload(
    proposal: Any, *, resources: Mapping[str, AuthoritativeResource]
) -> dict[str, Any] | None:
    if proposal is None:
        return None
    typed = proposal.proposal
    resource = resources.get(typed.target_resource)
    return {
        "proposal_id": typed.proposal_id,
        "action_type": typed.action_type.value,
        "target_resource": typed.target_resource,
        "amount_minor": typed.requested_amount_minor,
        "currency": typed.currency,
        "rationale": typed.rationale,
        "evidence_references": list(typed.evidence_references),
        "canonical_action_id": proposal.canonical_action_identity,
        "current_resource_state": None if resource is None else resource.state,
        "reversibility": "reversible simulator action",
        "customer_impact": "low; simulator only",
        "proposer_id": f"analysis:{typed.analysis_id}",
        "parameters": dict(typed.parameters),
    }


def _proposal_confidence(
    result: DeterministicAnalysisResult, proposal: TypedActionProposal
) -> float:
    values = [
        item.confidence
        for item in result.attributions
        if item.timeline_event_id in set(proposal.attribution_references)
    ]
    return min(values) if values else 0.0


def _agent_payload_from_audit(
    audit: ModelAnalysisAudit, environment: str, run_id: str
) -> dict[str, Any]:
    provenance = dict(audit.provenance)
    return {
        "run_id": run_id,
        "tenant_id": audit.tenant_id,
        "case_id": audit.case_id,
        "correlation_id": audit.correlation_id,
        "execution_mode": "fresh_agent",
        "provider_mode": "live",
        "action_environment": environment,
        "profile": "reclaim-specialist",
        "provider": audit.provider,
        "model": audit.model,
        "status": "completed" if audit.response_checksum else "unavailable",
        "analysis": provenance.get("typed_response"),
        "proposal_validation": {
            item.proposal.proposal_id: item.as_dict() for item in audit.proposals
        },
        "policy_result": None,
        "error": audit.fallback_reason,
        "provenance": {
            "prompt_version": str(provenance.get("prompt_version", "unknown")),
            "harness_version": str(provenance.get("harness_version", "unknown")),
            "parser_version": str(audit.parser_version or "unknown"),
            "runtime_version": str(provenance.get("runtime_version", "unknown")),
            "request_checksum": audit.request_checksum,
            "response_checksum": audit.response_checksum,
            "token_count": audit.token_count,
            "estimated_cost": audit.estimated_cost,
            "fresh_execution_observed": bool(provenance.get("attempted_providers")),
            "attempted_providers": list(provenance.get("attempted_providers", ())),
        },
        "remote_side_effects": [],
    }


def _agent_analysis_payload(audit: ModelAnalysisAudit | None) -> dict[str, Any] | None:
    """Project the latest persisted typed analysis into the case read model.

    The model-run audit already contains redacted structured output.  Select only
    the fields the operator needs so raw provider text and arbitrary provenance
    values cannot leak through the case-detail API.
    """

    if audit is None:
        return None
    typed_response = audit.provenance.get("typed_response", {})
    typed = typed_response if isinstance(typed_response, Mapping) else {}
    attributions = typed.get("attributions", ())
    safe_attributions = [
        {
            "timeline_event_id": str(item["timeline_event_id"]),
            "label": str(item["label"]),
            "confidence": float(item["confidence"]),
            "rationale": str(item["rationale"]),
            "evidence_references": [str(ref) for ref in item.get("evidence_references", ())],
        }
        for item in attributions
        if isinstance(item, Mapping)
        and all(key in item for key in ("timeline_event_id", "label", "confidence", "rationale"))
    ]
    return {
        "analysis_id": audit.analysis_id,
        "run_id": audit.provenance.get("agent_run_id"),
        "status": audit.terminal_outcome,
        "mode": audit.mode,
        "provider": audit.provider,
        "model": audit.model,
        "uncertainty": [str(item) for item in audit.uncertainty],
        "attributions": safe_attributions,
        "refusal_records": [str(item) for item in audit.refusal_records],
        "provenance": {
            "authoritative_store": "postgresql",
            "request_checksum": audit.request_checksum,
            "response_checksum": audit.response_checksum,
            "deterministic_analysis_checksum": audit.deterministic_analysis_checksum,
            "deterministic_exposure_checksum": audit.deterministic_exposure_checksum,
        },
    }


def _timeline_from_row(row: Any) -> TimelineEvent:
    payload = _json_value(row[8])
    provenance = payload.get("_reclaim_provenance", {}) if isinstance(payload, Mapping) else {}
    source_event_ids = tuple(_json_value(row[4]) or ())
    source_event_id = str(
        provenance.get("source_event_id") or (source_event_ids[0] if source_event_ids else row[1])
    )
    return TimelineEvent(
        tenant_id=str(row[0]),
        case_id=str(row[2]),
        timeline_event_id=str(row[1]),
        canonical_event_type=str(row[3]),
        source_event_ids=source_event_ids,
        source_event_id=source_event_id,
        source_identity=str(provenance.get("source_identity", "postgresql-authoritative")),
        effective_at=_as_datetime(row[5]),
        observed_at=_as_datetime(provenance.get("observed_at", row[5])),
        received_at=_as_datetime(provenance.get("received_at", row[5])),
        ordering_key=str(row[6]),
        dedupe_key=str(row[7]),
        event_payload=payload,
        evidence_references=tuple(_json_value(row[9]) or ()),
        conflicting_source_event_ids=tuple(_json_value(row[10]) or ()),
        uncertainty_reasons=tuple(_json_value(row[11]) or ()),
    )


def _evidence_payload_row(row: Any) -> dict[str, Any]:
    return {
        "tenant_id": str(row[0]),
        "evidence_id": str(row[1]),
        "case_id": str(row[2]),
        "connector_id": str(row[3]),
        "resource_type": str(row[4]),
        "completeness": str(row[5]),
        "checksum": row[6],
    }


def _timeline_payload(row: Any, attribution: Any | None) -> dict[str, Any]:
    payload = _json_value(row[8])
    provenance = payload.get("_reclaim_provenance", {}) if isinstance(payload, Mapping) else {}
    result = {
        "event_id": str(row[1]),
        "occurred_at": _iso(row[5]),
        "effective_at": _iso(row[5]),
        "observed_at": str(provenance.get("observed_at", _iso(row[5]))),
        "canonical_event_type": str(row[3]),
        "resource": str(payload.get("resource_id", "merchant"))
        if isinstance(payload, Mapping)
        else "merchant",
        "source_identity": str(provenance.get("source_identity", "postgresql-authoritative")),
        "attribution": None if attribution is None else str(attribution[3]),
        "confidence": None if attribution is None else float(attribution[4]),
        "rationale": None if attribution is None else str(attribution[5]),
        "evidence_references": list(_json_value(row[9]) or ()),
        "provenance": {
            "method": None if attribution is None else str(attribution[6]),
            "version": None if attribution is None else str(attribution[7]),
            "source": str(provenance.get("source_identity", "postgresql-authoritative")),
        },
        "financial_impact_minor": payload.get("amount_minor")
        if isinstance(payload, Mapping)
        else None,
        "currency": payload.get("currency") if isinstance(payload, Mapping) else None,
        "uncertainty_reasons": list(_json_value(row[11]) or ()),
        "source_event_ids": list(_json_value(row[4]) or ()),
    }
    return {key: value for key, value in result.items() if value is not None}


def _exposure_payload(rows: list[Any]) -> dict[str, Any]:
    if not rows:
        return {
            "currency": "INR",
            "gross_exposure_minor": 0,
            "recoverable_value_minor": 0,
            "contained_value_minor": 0,
            "legitimate_value_disrupted_minor": 0,
            "irreversible_loss_minor": 0,
            "remaining_exposure_minor": 0,
            "calculation_version": "exposure-v1.0.0",
            "source_references": [],
            "by_currency": [],
        }
    row = rows[-1]
    return {
        "currency": str(row[3]),
        "gross_exposure_minor": int(row[4]),
        "recoverable_value_minor": int(row[5]),
        "contained_value_minor": int(row[6]),
        "legitimate_value_disrupted_minor": int(row[7]),
        "irreversible_loss_minor": int(row[8]),
        "remaining_exposure_minor": int(row[9]),
        "calculation_version": str(row[10]),
        "source_references": list(_json_value(row[11]) or ()),
        "by_currency": [],
    }


def _execution_payload(execution: Any) -> dict[str, Any]:
    return {
        "status": execution.status.value
        if hasattr(execution.status, "value")
        else str(execution.status),
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "reconciliation_state": execution.reconciliation_state,
        "verification_state": "verified" if str(execution.status).startswith("verified") else None,
        "remote_reference": execution.remote_reference,
        "attempt_count": execution.attempt_count,
        "last_reconciled_at": _iso(execution.last_reconciled_at)
        if execution.last_reconciled_at
        else None,
        "result_reference": execution.result_reference,
        "simulation": True,
    }


def _verification_payload(row: Any) -> dict[str, Any]:
    return {
        "status": str(row[12]),
        "observed_resource_state": str(row[8]),
        "verifier_source": str(row[9]),
        "verification_version": str(row[11]),
        "evidence_references": list(_json_value(row[13]) or ()),
        "recorded_at": _iso(row[15]),
        "checksum": row[14],
    }


def _escalation_payload(row: Any) -> dict[str, Any]:
    return {
        "escalation_id": str(row[1]),
        "state": str(row[17]),
        "owner_id": str(row[3]),
        "reason": str(row[5]),
        "remaining_exposure_minor": int(row[6]),
        "currency": str(row[7]),
        "evidence_references": list(_json_value(row[8]) or ()),
        "recommended_human_decision": str(row[9]),
        "expected_version": 0,
        "canonical_action_id": row[10],
        "execution_id": row[11],
        "verification_id": row[12],
        "policy_version_id": row[13],
    }


def _reported_incident_payload(incident: Any | None) -> dict[str, Any] | None:
    """Expose typed intake metadata without returning the raw narrative."""

    if incident is None:
        return None
    return {
        "source": str(incident[2]),
        "incident_type": str(incident[10] or "other"),
        "occurred_at": _iso(incident[11] or incident[4]),
        "customer_reference": None if incident[13] is None else str(incident[13]),
        "account_reference": None if incident[14] is None else str(incident[14]),
        "order_reference": None if incident[15] is None else str(incident[15]),
        "payment_reference": None if incident[16] is None else str(incident[16]),
        "reported_amount_minor": incident[17],
        "reported_currency": None if incident[18] is None else str(incident[18]),
        "external_reference": None if incident[19] is None else str(incident[19]),
        "report_reference": None if incident[6] is None else str(incident[6]),
        "narrative_checksum": None if incident[12] is None else str(incident[12]),
        "reported_value_status": "unverified",
    }


def _orchestration_payload(record: Any | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "run_id": record.run_id,
        "workflow_version": record.workflow_version,
        "external_execution_id": record.external_execution_id,
        "stage": record.stage.value,
        "status": record.status.value,
        "queued_at": _iso(record.queued_at),
        "started_at": None if record.started_at is None else _iso(record.started_at),
        "completed_at": None if record.completed_at is None else _iso(record.completed_at),
        "updated_at": _iso(record.updated_at),
        "failure_code": record.failure_code,
    }


def _policy_payload(decision: PolicyDecision) -> dict[str, Any]:
    conditions = decision.evaluated_conditions
    reasons = conditions.get("failure_reasons", ()) if isinstance(conditions, Mapping) else ()
    return {
        "result": decision.result.value,
        "policy_version_id": decision.policy_version_id,
        "evaluator_version": decision.evaluator_version,
        "evaluated_at": decision.decided_at.isoformat(),
        "reason": "; ".join(str(item) for item in reasons)
        or "Deterministic policy evaluation recorded.",
        "evaluated_conditions": conditions,
    }


def _approval_payload(
    uow: PostgresUnitOfWork,
    tenant_id: str,
    case_id: str,
    proposal: Mapping[str, Any],
    policy: Mapping[str, Any],
    audit: ModelAnalysisAudit | None,
) -> dict[str, Any]:
    approval = _approval_for_proposal(uow, tenant_id, str(proposal["proposal_id"]))
    if approval is not None:
        return {
            **approval.model_dump(mode="json"),
            "request_id": _approval_request_id(
                _typed_proposal_from_row(
                    _action_proposal_row(uow, case_id, str(proposal["proposal_id"])),
                    _case_correlation(uow, case_id),
                ),
                _policy_version_from_row(
                    uow.policy_versions.get(policy_version_id=str(policy["policy_version_id"]))
                ),
            ),
            "expected_version": 0,
        }
    if policy.get("result") != PolicyResult.APPROVAL_REQUIRED.value:
        return {"status": "not_required", "expected_version": 0}
    proposer = f"analysis:{audit.analysis_id}" if audit is not None else "fresh-agent"
    return {
        "status": "pending",
        "request_id": f"approval-request:{proposal['proposal_id']}:{policy['policy_version_id']}",
        "proposer_id": proposer,
        "policy_version_id": policy["policy_version_id"],
        "expected_version": 0,
        "reason": "Independent authenticated approver required before simulator submission.",
    }


def _audit_payload(row: Any) -> dict[str, Any]:
    return {
        "audit_id": str(row[2]),
        "recorded_at": _iso(row[16]),
        "actor": str(row[4]),
        "action": str(row[5]),
        "outcome": str(row[15]),
        "input_references": list(row[6] or ()),
        "output_references": list(row[7] or ()),
        "evidence_references": list(row[8] or ()),
        "policy_version_id": row[9],
        "model_version": row[10],
        "provider_version": row[11],
        "approval_id": row[12],
        "execution_id": row[13],
        "correlation_ids": list(row[14] or ()),
        "previous_record_checksum": row[17],
        "record_checksum": str(row[18]),
        "narrative": f"{row[5]} recorded by the authoritative local runtime.",
    }


def _next_decision(state: str, approval: Any, action: Any, verification: Any) -> str:
    if verification and verification.get("status") == "inconclusive":
        return "Verification is inconclusive; review the tenant-scoped escalation."
    if action and action.get("status") == "unknown":
        return "UNKNOWN remote result; reconcile before any retry."
    if approval and approval.get("status") in {"pending", "required"}:
        return "An independent approver must approve the exact action packet."
    if state == "timeline_ready":
        return "Run the fresh agent to create a typed analysis and policy-bound proposal."
    if state in {"action_pending", "analyzed"}:
        return "Review the exact proposal, then approve and submit it to the simulator."
    if state == "verified_contained":
        return "Containment was verified; inspect the append-only audit trace."
    return "Review the authoritative case state and audit trace."


def _local_authorize(
    verifier: Any, authorization: str | None, tenant_id: str, role: RequiredRole
) -> Any:
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return verifier.authorize(token.strip(), tenant_id=tenant_id, required_role=role)
    except Exception as exc:
        raise HTTPException(status_code=403, detail="local demo authorization is required") from exc


def _postgres_connection_factory(settings: Settings) -> ConnectionFactory:
    def connect() -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised in a configured container
            raise LocalRuntimeError(
                "PostgreSQL driver is unavailable; install psycopg[binary]"
            ) from exc
        return psycopg.connect(settings.database_url)

    return connect


def _service_context(tenant_id: str) -> TenantAuthorizationContext:
    return _user_context(
        tenant_id,
        "local-runtime-service",
        {
            RequiredRole.REVIEWER.value,
            RequiredRole.APPROVER.value,
            RequiredRole.ESCALATION_OWNER.value,
            RequiredRole.POLICY_OWNER.value,
        },
        identity_type=IdentityType.SERVICE,
    )


def _action_gateway_context(tenant_id: str) -> TenantAuthorizationContext:
    return _user_context(
        tenant_id,
        "local-action-gateway",
        {RequiredRole.REVIEWER.value},
        identity_type=IdentityType.SERVICE,
    )


def _user_context(
    tenant_id: str,
    subject: str,
    roles: set[str] | frozenset[str],
    *,
    identity_type: IdentityType = IdentityType.USER,
) -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject=subject,
        tenant_id=tenant_id,
        roles=frozenset(roles),
        identity_type=identity_type,
        issuer="local-demo",
    )


def _load_seed_fixture() -> Mapping[str, Any]:
    path = (
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "canonical" / "incident.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp is required")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(UTC)


def _utc(value: Any) -> datetime:
    return _as_datetime(value)


def _iso(value: Any) -> str:
    return _as_datetime(value).isoformat().replace("+00:00", "Z")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]


__all__ = [
    "LocalDemoRuntime",
    "LocalRuntimeError",
    "create_local_runtime_router",
]
