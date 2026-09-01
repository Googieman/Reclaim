"""T103 US3 vertical-slice gate.

This gate is deliberately deterministic.  It exercises the production seams
with replay-labeled connector simulators and in-memory authority doubles; it
does not claim PostgreSQL, Temporal, Redpanda, or live merchant execution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from action_gateway.idempotency import InMemoryActionExecutionStore
from action_gateway.reconciliation import recover_action
from action_gateway.service import ActionGateway, ActionGatewayError
from action_gateway.verification import VerificationService, verify_and_route
from analysis.proposal_validator import (
    AuthoritativeAttribution,
    AuthoritativeResource,
    ProposalValidationContext,
    ProposalValidationStatus,
    ProposalValidator,
)
from api.control_plane import ControlPlaneError, submit_action
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.config import Settings
from app.control_plane.tenant_config import TenantConfiguration
from app.events.action_events import build_action_event, build_case_terminal_event
from app.events.policy_events import (
    build_approval_recorded_event,
    build_policy_decision_event,
)
from app.audit.actions import persist_action_audit
from app.audit.chain import AuditChain
from approvals.service import ApprovalError, ApprovalService
from cases.terminal_states import TerminalStateError, transition_case
from connectors.actions.manifests import build_action_manifests
from connectors.simulators.actions import (
    ActionSimulatorScenario,
    DeterministicActionSimulator,
)
from finance.exposure import calculate_exposure
from policy.evaluator import evaluate_policy
from policy.tenant_configuration import validate_tenant_policy_configuration
from policy.versions import build_policy_version, publish_policy_version
from workflows.activities.containment import (
    CONTAINMENT_STAGE_ORDER,
    ContainmentActivityError,
    ContainmentPipeline,
    run_containment,
)
from workflows.commands import CaseWorkflowCommand

from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayRequest,
    VerificationResult,
)
from packages.contracts.analysis_policy import (
    ActionType,
    AttributionLabel,
    ModelAnalysisRequest,
    ModelBudget,
    PolicyResult,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.audit_replay import AuditRecord
from packages.contracts.connectors import (
    ActionConnectorResponse,
    ActionConnectorResult,
)
from packages.contracts.events import EventType


TENANT = "tenant-us3-t103"
CASE = "case-us3-t103"
CORRELATION = "corr-us3-t103"
ANALYSIS = "analysis-us3-t103"
POLICY_ID = "policy-us3-t103"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
EVIDENCE = ("evidence-incident-us3", "evidence-payment-us3")


def _context(
    subject: str,
    role: str,
    *,
    identity_type: IdentityType = IdentityType.USER,
) -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject=subject,
        tenant_id=TENANT,
        roles=frozenset({role}),
        identity_type=identity_type,
        issuer="us3-t103-test",
    )


class RecordingSimulator:
    """Count connector calls/effects while retaining the simulator contract."""

    def __init__(self, simulator: DeterministicActionSimulator) -> None:
        self.simulator = simulator
        self.manifest = simulator.manifest
        self.calls = 0
        self.remote_effects = 0
        self._effect_keys: set[str] = set()

    def execute(
        self, request: Any, *, credentials: Any = None
    ) -> ActionConnectorResponse:
        self.calls += 1
        response = self.simulator.execute(request, credentials=credentials)
        if (
            response.result
            in {
                ActionConnectorResult.ACCEPTED,
                ActionConnectorResult.COMPLETED,
                ActionConnectorResult.UNKNOWN,
            }
            and request.idempotency_key not in self._effect_keys
        ):
            self._effect_keys.add(request.idempotency_key)
            self.remote_effects += 1
        return response


class ReconciliationProbe:
    """A late-response seam that proves recovery does not invoke again."""

    def __init__(self) -> None:
        self.invoke_calls = 0
        self.reconcile_calls = 0

    def invoke(self, idempotency_key: str) -> str:
        self.invoke_calls += 1
        raise AssertionError(
            f"recovery retried before reconciliation: {idempotency_key}"
        )

    def reconcile(self, idempotency_key: str) -> str:
        assert idempotency_key.startswith("provider:")
        self.reconcile_calls += 1
        return "completed"


class ReplayMerchantState:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states

    def observe(self, request: ActionGatewayRequest) -> dict[str, str]:
        return {
            "state": self.states[request.target_resource],
            "source": "replay-merchant-state",
        }


class InMemoryAuditRepository:
    """Append-only test authority implementing the AuditChain protocol."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def lock_chain(self, *, tenant_id: str) -> None:
        assert tenant_id == TENANT

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        assert tenant_id == TENANT
        return self.records[-1].record_checksum if self.records else None

    def checksum_for_audit_id(self, *, tenant_id: str, audit_id: str) -> str | None:
        assert tenant_id == TENANT
        for record in self.records:
            if record.audit_id == audit_id:
                return record.record_checksum
        return None

    def append(self, record: AuditRecord) -> AuditRecord:
        for existing in self.records:
            if existing.audit_id == record.audit_id:
                if existing != record:
                    raise AssertionError("audit mutation was accepted")
                return record
        assert record.tenant_id == TENANT
        assert record.previous_record_checksum == self.latest_checksum(tenant_id=TENANT)
        self.records.append(record)
        return record


class InMemoryOutbox:
    def __init__(self) -> None:
        self.events: dict[str, Any] = {}

    def append(self, event: Any) -> None:
        assert event.tenant_id == TENANT
        assert event.payload.get("case_id") == CASE
        existing = self.events.get(event.event_id)
        if existing is not None and existing != event:
            raise AssertionError("outbox event mutation was accepted")
        self.events[event.event_id] = event


def _policy() -> Any:
    config = validate_tenant_policy_configuration(
        tenant_id=TENANT,
        change="publish-us3-t103",
        thresholds={"min_confidence": 0.95, "max_amount_minor": 100_000},
        action_allowlist=tuple(action.value for action in ActionType),
        actor_role="policy-owner",
    )
    assert config.accepted is True
    draft = build_policy_version(
        policy_version_id=POLICY_ID,
        tenant_id=TENANT,
        thresholds=config.thresholds,
        action_allowlist=config.action_allowlist,
        approval_rules={},
        effective_from=NOW - timedelta(minutes=1),
        effective_to=None,
        author="policy-owner-us3",
    )
    return publish_policy_version(
        draft,
        authorization_context=_context("policy-owner-us3", "policy-owner"),
    )


def _proposal_context() -> tuple[ProposalValidationContext, ModelAnalysisRequest]:
    manifests = build_action_manifests(TENANT)
    resources = {
        "session-us3-t103": AuthoritativeResource(
            resource_id="session-us3-t103",
            resource_type="sessions",
            tenant_id=TENANT,
            case_id=CASE,
            state="active",
            connector_id="session-actions",
            evidence_references=(EVIDENCE[0],),
            timeline_event_ids=("timeline-session-us3",),
        ),
        "fulfillment-us3-t103": AuthoritativeResource(
            resource_id="fulfillment-us3-t103",
            resource_type="fulfillment",
            tenant_id=TENANT,
            case_id=CASE,
            state="ready",
            connector_id="fulfillment-actions",
            evidence_references=(EVIDENCE[0],),
            timeline_event_ids=("timeline-fulfillment-us3",),
        ),
    }
    timeline_events = {
        "timeline-session-us3": {
            "timeline_event_id": "timeline-session-us3",
            "tenant_id": TENANT,
            "case_id": CASE,
            "evidence_references": (EVIDENCE[0],),
            "event_payload": {"resource_id": "session-us3-t103"},
        },
        "timeline-fulfillment-us3": {
            "timeline_event_id": "timeline-fulfillment-us3",
            "tenant_id": TENANT,
            "case_id": CASE,
            "evidence_references": (EVIDENCE[0],),
            "event_payload": {"resource_id": "fulfillment-us3-t103"},
        },
    }
    attributions = {
        event_id: AuthoritativeAttribution(
            timeline_event_id=event_id,
            label=AttributionLabel.MALICIOUS,
            confidence=0.99,
            tenant_id=TENANT,
            case_id=CASE,
            evidence_references=(EVIDENCE[0],),
            rationale="Replay fixture attribution is linked to authoritative evidence.",
            method="rules",
            model_or_rules_version="rules-us3-t103-v1",
        )
        for event_id in timeline_events
    }
    analysis_request = ModelAnalysisRequest(
        tenant_id=TENANT,
        correlation_id=CORRELATION,
        case_id=CASE,
        redacted_case_representation={"incident_reference": "incident-us3-t103"},
        evidence_references=EVIDENCE,
        allowed_tools=("read_evidence", "propose_action"),
        policy_version_id=POLICY_ID,
        budget=ModelBudget(max_tokens=500, max_tool_calls=2, timeout_seconds=30),
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )
    return (
        ProposalValidationContext(
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            analysis_id=ANALYSIS,
            evidence_references=frozenset(EVIDENCE),
            timeline_events=timeline_events,
            attributions=attributions,
            resources=resources,
            connectors=manifests,
            action_connector_ids={
                ActionType.REVOKE_SUSPICIOUS_SESSION.value: "session-actions",
                ActionType.HOLD_FULFILLMENT.value: "fulfillment-actions",
            },
            analysis_request=analysis_request,
            provider_mode=ProviderMode.REPLAY,
            replay_label=ProviderMode.REPLAY,
        ),
        analysis_request,
    )


def _proposal(
    action: ActionType, target: str, timeline: str, proposal_id: str
) -> TypedActionProposal:
    return TypedActionProposal(
        tenant_id=TENANT,
        correlation_id=CORRELATION,
        proposal_id=proposal_id,
        case_id=CASE,
        action_type=action,
        target_resource=target,
        parameters={"reason": "replay-confirmed containment"},
        rationale="Typed proposal linked to authoritative replay evidence.",
        evidence_references=(EVIDENCE[0],),
        attribution_references=(timeline,),
        idempotency_key=f"supplied-{proposal_id}",
        analysis_id=ANALYSIS,
    )


def _request(
    proposal: TypedActionProposal,
    *,
    canonical_action_id: str,
    decision_id: str,
    checksum: str,
) -> ActionGatewayRequest:
    return ActionGatewayRequest(
        tenant_id=TENANT,
        correlation_id=CORRELATION,
        case_id=CASE,
        proposal_id=proposal.proposal_id,
        action_type=proposal.action_type,
        connector_id=(
            "session-actions"
            if proposal.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
            else "fulfillment-actions"
        ),
        operation=proposal.action_type.value,
        target_resource=proposal.target_resource,
        parameters=proposal.parameters,
        policy_decision_id=decision_id,
        policy_version_id=POLICY_ID,
        idempotency_key=canonical_action_id,
        causation_id=proposal.proposal_id,
        request_checksum=checksum,
        requested_at=NOW,
    )


def _resource(proposal: TypedActionProposal) -> dict[str, str]:
    return {
        "tenant_id": TENANT,
        "case_id": CASE,
        "resource_id": proposal.target_resource,
        "resource_type": (
            "sessions"
            if proposal.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
            else "fulfillment"
        ),
        "connector_id": (
            "session-actions"
            if proposal.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
            else "fulfillment-actions"
        ),
        "state": "active"
        if proposal.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
        else "ready",
    }


def _decision(policy: Any, proposal: TypedActionProposal) -> Any:
    return evaluate_policy(
        policy_version=policy,
        tenant_id=TENANT,
        case_id=CASE,
        proposal_id=proposal.proposal_id,
        correlation_id=CORRELATION,
        action=proposal.action_type.value,
        confidence=0.99,
        resource=_resource(proposal),
        amount_minor=0,
        is_reversible=True,
        customer_impact={"class": "low"},
        evaluated_at=NOW,
    )


def _run_session_pipeline(
    *,
    gateway: ActionGateway,
    store: InMemoryActionExecutionStore,
    request: ActionGatewayRequest,
    duplicate_request: ActionGatewayRequest,
    decision: Any,
    duplicate_decision: Any,
    session_proposal: TypedActionProposal,
    canonical_action_id: str,
    reviewer_context: TenantAuthorizationContext,
    service_context: TenantAuthorizationContext,
    verifier: ReplayMerchantState,
    recovery_probe: ReconciliationProbe,
) -> tuple[dict[str, Any], Any, Any]:
    values: dict[str, Any] = {}

    def typed(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"proposal_id": session_proposal.proposal_id}

    def policy(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"policy_decision_id": decision.decision_id}

    def approval(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"approval_id": None}

    def canonical(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"canonical_action_id": canonical_action_id}

    def action_gateway(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        first = submit_action(
            request=request,
            gateway=gateway,
            policy_decision=decision,
            authoritative_resource=_resource(session_proposal),
            authorization_context=reviewer_context,
            gateway_authorization_context=service_context,
            canonical_action_id=canonical_action_id,
            execution_store=store,
        )
        duplicate = submit_action(
            request=duplicate_request,
            gateway=gateway,
            policy_decision=duplicate_decision,
            authoritative_resource=_resource(session_proposal),
            authorization_context=reviewer_context,
            gateway_authorization_context=service_context,
            canonical_action_id=canonical_action_id,
            execution_store=store,
        )
        assert first.state is ActionExecutionState.UNKNOWN
        assert duplicate.state is ActionExecutionState.UNKNOWN
        assert duplicate.execution_id == first.execution_id
        assert (
            store.get(tenant_id=TENANT, canonical_action_id=canonical_action_id).status
            is ActionExecutionState.UNKNOWN
        )
        assert gateway._connectors["session-actions"].calls == 1
        values.update(first_response=first, duplicate_response=duplicate)
        return {"execution_id": first.execution_id, "action_state": first.state.value}

    def execution_persistence(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        record = store.get(tenant_id=TENANT, canonical_action_id=canonical_action_id)
        assert record is not None
        assert record.attempt_count == 1
        return {
            "execution_persistence": "authoritative-test-store",
            "execution_id": record.execution_id,
        }

    def unknown_reconciliation(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        recovery = recover_action(
            request=request,
            remote=recovery_probe,
            process_restart=True,
            timeout=True,
            duplicate_deliveries=2,
            late_remote_response=True,
            store=store,
        )
        assert recovery.reconciliation_performed is True
        assert recovery.retry_before_reconciliation is False
        assert recovery.retry_performed is False
        assert recovery.effect_occurred is True
        assert recovery.attempt_count == 1
        assert recovery_probe.invoke_calls == 0
        assert recovery_probe.reconcile_calls == 1
        values["recovery"] = recovery
        return {"reconciliation": recovery.remote_state}

    def merchant_verification(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        execution = store.get(tenant_id=TENANT, canonical_action_id=canonical_action_id)
        assert execution is not None
        route = VerificationService(verifier).verify(
            request=request,
            execution=execution,
            evidence_references=(EVIDENCE[0],),
            verification_id="verification-session-us3-t103",
            observed_at=NOW,
        )
        assert route.verification.result is VerificationResult.VERIFIED_SUCCESS
        assert route.terminal_state == "verified_contained"
        assert route.verification.canonical_action_id == canonical_action_id
        assert route.verification.connector_id == "session-actions"
        assert route.verification.resource_type == "sessions"
        values["verification_route"] = route
        return {"verification_id": route.verification.verification_id}

    def escalation(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"escalation": None}

    def terminal(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        route = values["verification_route"]
        transition = transition_case(
            current_state="containing",
            requested_state="verified_contained",
            tenant_id=TENANT,
            case_id=CASE,
            action_id=canonical_action_id,
            execution_id=route.verification.execution_id,
            verification_id=route.verification.verification_id,
            verification_result=route.verification.result.value,
            required_actions_completed=True,
            unresolved=False,
        )
        values["terminal_transition"] = transition
        return {"terminal_state": transition.state}

    pipeline = ContainmentPipeline(
        steps={
            "typed_proposal": typed,
            "policy_evaluation": policy,
            "approval": approval,
            "canonical_action": canonical,
            "action_gateway": action_gateway,
            "execution_persistence": execution_persistence,
            "unknown_reconciliation": unknown_reconciliation,
            "merchant_verification": merchant_verification,
            "escalation": escalation,
            "terminal_transition": terminal,
        }
    )
    command = CaseWorkflowCommand(
        tenant_id=TENANT,
        case_id=CASE,
        correlation_id=CORRELATION,
        command_id="command-session-us3-t103",
        expected_state="containing",
        stages=("run_containment",),
        metadata={"mode": "replay", "label": "replay"},
    )
    result = run_containment(
        command,
        runner=pipeline,
        authorization_context=service_context,
    )
    assert tuple(result["completed_stages"]) == CONTAINMENT_STAGE_ORDER
    assert result["terminal_state"] == "verified_contained"
    return result, values["first_response"], values["verification_route"]


def _run_hold_pipeline(
    *,
    gateway: ActionGateway,
    store: InMemoryActionExecutionStore,
    request: ActionGatewayRequest,
    decision: Any,
    proposal: TypedActionProposal,
    canonical_action_id: str,
    service_context: TenantAuthorizationContext,
    verifier: ReplayMerchantState,
    exposure: Any,
) -> tuple[dict[str, Any], Any, Any]:
    values: dict[str, Any] = {}

    def typed(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"proposal_id": proposal.proposal_id}

    def policy(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"policy_decision_id": decision.decision_id}

    def approval(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"approval_id": None}

    def canonical(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"canonical_action_id": canonical_action_id}

    def action_gateway(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        response = submit_action(
            request=request,
            gateway=gateway,
            policy_decision=decision,
            authoritative_resource=_resource(proposal),
            authorization_context=_context("reviewer-us3", "reviewer"),
            gateway_authorization_context=service_context,
            canonical_action_id=canonical_action_id,
            execution_store=store,
        )
        assert response.state is ActionExecutionState.COMPLETED
        values["response"] = response
        return {
            "execution_id": response.execution_id,
            "action_state": response.state.value,
        }

    def execution_persistence(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        record = store.get(tenant_id=TENANT, canonical_action_id=canonical_action_id)
        assert record is not None
        assert record.status is ActionExecutionState.COMPLETED
        return {"execution_persistence": "authoritative-test-store"}

    def unknown_reconciliation(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        return {"reconciliation": "not_required"}

    def merchant_verification(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        execution = store.get(tenant_id=TENANT, canonical_action_id=canonical_action_id)
        assert execution is not None
        route = VerificationService(verifier).verify(
            request=request,
            execution=execution,
            evidence_references=(EVIDENCE[0],),
            verification_id="verification-fulfillment-us3-t103",
            observed_at=NOW,
        )
        assert route.verification.result is VerificationResult.INCONCLUSIVE
        values["verification_route"] = route
        return {"verification_id": route.verification.verification_id}

    def escalation(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        route = values["verification_route"]
        routed = verify_and_route(
            verification=route.verification,
            escalation_owner="escalation-owner-us3",
            owner_tenant_id=TENANT,
            remaining_exposure_minor=exposure.remaining_exposure_minor,
            currency=exposure.currency,
            evidence_references=(EVIDENCE[0],),
            recommended_human_decision="reconcile merchant state and decide containment",
            case_id=CASE,
            canonical_action_id=canonical_action_id,
            policy_version_id=POLICY_ID,
        )
        assert routed.terminal_state == "escalated_unresolved"
        assert routed.escalation is not None
        assert (
            routed.escalation.remaining_exposure_minor
            == exposure.remaining_exposure_minor
        )
        assert routed.escalation.currency == "INR"
        values["routed"] = routed
        return {"escalation_id": routed.escalation.escalation_id}

    def terminal(_command: Any, _state: dict[str, Any]) -> dict[str, Any]:
        routed = values["routed"]
        transition = transition_case(
            current_state="containing",
            requested_state="escalated_unresolved",
            tenant_id=TENANT,
            case_id=CASE,
            action_id=canonical_action_id,
            execution_id=routed.verification.execution_id,
            verification_id=routed.verification.verification_id,
            escalation_id=routed.escalation.escalation_id,
            verification_result=routed.verification.result.value,
            unresolved=True,
            remaining_exposure_minor=exposure.remaining_exposure_minor,
            currency=exposure.currency,
        )
        values["terminal_transition"] = transition
        return {"terminal_state": transition.state}

    pipeline = ContainmentPipeline(
        steps={
            "typed_proposal": typed,
            "policy_evaluation": policy,
            "approval": approval,
            "canonical_action": canonical,
            "action_gateway": action_gateway,
            "execution_persistence": execution_persistence,
            "unknown_reconciliation": unknown_reconciliation,
            "merchant_verification": merchant_verification,
            "escalation": escalation,
            "terminal_transition": terminal,
        }
    )
    command = CaseWorkflowCommand(
        tenant_id=TENANT,
        case_id=CASE,
        correlation_id=CORRELATION,
        command_id="command-fulfillment-us3-t103",
        expected_state="containing",
        stages=("run_containment",),
        metadata={"mode": "replay", "label": "replay"},
    )
    result = run_containment(
        command, runner=pipeline, authorization_context=service_context
    )
    assert tuple(result["completed_stages"]) == CONTAINMENT_STAGE_ORDER
    assert result["terminal_state"] == "escalated_unresolved"
    return result, values["response"], values["routed"]


def _append_audit_trace(
    repository: InMemoryAuditRepository,
    *,
    session_proposal: TypedActionProposal,
    hold_proposal: TypedActionProposal,
    policy: Any,
    approval: Any,
    session_response: Any,
    session_route: Any,
    hold_response: Any,
    hold_route: Any,
    exposure: Any,
) -> None:
    chain = AuditChain(repository)
    stages = (
        ("incident", (), (), EVIDENCE, "accepted"),
        ("evidence", ("incident-us3-t103",), (), EVIDENCE, "collected"),
        ("attribution", (EVIDENCE[0],), (), EVIDENCE, "malicious"),
        (
            "exposure",
            tuple(exposure.payment_references),
            (),
            exposure.source_references,
            "calculated",
        ),
        (
            "proposal",
            (),
            (session_proposal.proposal_id, hold_proposal.proposal_id),
            EVIDENCE,
            "typed",
        ),
        ("policy", (POLICY_ID,), (), EVIDENCE, "evaluated"),
        ("approval", (approval.approval_id,), (), EVIDENCE, "approved"),
        (
            "canonical_action",
            (),
            (session_response.idempotency_key, hold_response.idempotency_key),
            EVIDENCE,
            "derived",
        ),
        (
            "execution",
            (),
            (session_response.execution_id, hold_response.execution_id),
            EVIDENCE,
            "submitted",
        ),
        (
            "verification",
            (),
            (
                session_route.verification.verification_id,
                hold_route.verification.verification_id,
            ),
            EVIDENCE,
            "completed",
        ),
        (
            "escalation",
            (),
            (hold_route.escalation.escalation_id,),
            EVIDENCE,
            "open",
        ),
        (
            "terminal",
            (),
            ("verified_contained", "escalated_unresolved"),
            EVIDENCE,
            "explicit_outcomes",
        ),
    )
    for index, (stage, inputs, outputs, evidence, outcome) in enumerate(stages):
        record = chain.build_record(
            tenant_id=TENANT,
            audit_id=f"audit:us3:t103:{index:02d}:{stage}",
            case_id=CASE,
            actor="us3-t103-gate",
            action=f"containment.{stage}",
            input_references=inputs,
            output_references=outputs,
            evidence_references=evidence,
            policy_version_id=POLICY_ID if stage in {"policy", "approval"} else None,
            approval_id=approval.approval_id if stage == "approval" else None,
            execution_id=session_response.execution_id
            if stage in {"execution", "verification"}
            else None,
            correlation_ids=(CORRELATION,),
            outcome=outcome,
            recorded_at=NOW + timedelta(seconds=index),
        )
        chain.append(record)

    for audit_id, action_id, execution_id, verification_id, escalation_id, outcome in (
        (
            "audit:us3:t103:action-session",
            session_response.idempotency_key,
            session_response.execution_id,
            session_route.verification.verification_id,
            None,
            "verified_contained",
        ),
        (
            "audit:us3:t103:action-fulfillment",
            hold_response.idempotency_key,
            hold_response.execution_id,
            hold_route.verification.verification_id,
            hold_route.escalation.escalation_id,
            "escalated_unresolved",
        ),
    ):
        action_audit = persist_action_audit(
            tenant_id=TENANT,
            case_id=CASE,
            action_id=action_id,
            execution_id=execution_id,
            verification_id=verification_id,
            escalation_id=escalation_id,
            policy_version_id=POLICY_ID,
            evidence_references=EVIDENCE,
            correlation_ids=(CORRELATION,),
            outcome=outcome,
            unit_of_work=None,
            audit_id=audit_id,
            recorded_at=NOW + timedelta(seconds=100),
        )
        chain.append(action_audit.audit_record)


def _append_outbox_trace(
    outbox: InMemoryOutbox,
    *,
    policy_decision: Any,
    approval: Any,
    session_request: ActionGatewayRequest,
    session_response: Any,
    recovery: Any,
    session_verification: Any,
    hold_request: ActionGatewayRequest,
    hold_response: Any,
    hold_verification: Any,
    escalation: Any,
    session_terminal: Any,
    hold_terminal: Any,
) -> None:
    for event in (
        build_policy_decision_event(
            policy_decision,
            policy_checksum=policy_decision.evaluated_conditions["policy_checksum"],
        ),
        build_approval_recorded_event(approval),
        build_action_event(
            event_type=EventType.ACTION_REQUESTED,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=session_request.causation_id,
            aggregate_id=CASE,
            payload={
                "case_id": CASE,
                "canonical_action_id": session_response.idempotency_key,
                "execution_id": session_response.execution_id,
                "connector_id": session_request.connector_id,
                "target_resource": session_request.target_resource,
            },
            occurred_at=NOW,
        ),
        build_action_event(
            event_type=EventType.ACTION_UNKNOWN,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=session_request.causation_id,
            aggregate_id=CASE,
            payload={
                "case_id": CASE,
                "execution_id": session_response.execution_id,
                "canonical_action_id": session_response.idempotency_key,
                "remote_state": "unknown",
                "reconciliation_required": True,
            },
            occurred_at=NOW + timedelta(seconds=1),
        ),
        build_action_event(
            event_type=EventType.ACTION_RECONCILED,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=session_request.causation_id,
            aggregate_id=CASE,
            payload={
                "case_id": CASE,
                "execution_id": recovery.execution_id,
                "canonical_action_id": recovery.idempotency_key,
                "remote_state": recovery.remote_state,
                "retry_before_reconciliation": recovery.retry_before_reconciliation,
            },
            occurred_at=NOW + timedelta(seconds=2),
        ),
        build_action_event(
            event_type=EventType.VERIFICATION_COMPLETED,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=session_verification.execution_id,
            aggregate_id=CASE,
            payload={"case_id": CASE, **session_verification.model_dump(mode="json")},
            occurred_at=NOW + timedelta(seconds=3),
        ),
        build_action_event(
            event_type=EventType.VERIFICATION_COMPLETED,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=hold_verification.execution_id,
            aggregate_id=CASE,
            payload={"case_id": CASE, **hold_verification.model_dump(mode="json")},
            occurred_at=NOW + timedelta(seconds=4),
        ),
        build_action_event(
            event_type=EventType.CASE_ESCALATED,
            tenant_id=TENANT,
            case_id=CASE,
            correlation_id=CORRELATION,
            causation_id=hold_verification.execution_id,
            aggregate_id=CASE,
            payload={
                "case_id": CASE,
                "escalation_id": escalation.escalation_id,
                "owner_id": escalation.owner_id,
                "remaining_exposure_minor": escalation.remaining_exposure_minor,
                "currency": escalation.currency,
            },
            occurred_at=NOW + timedelta(seconds=5),
        ),
        build_case_terminal_event(
            session_terminal, audit_reference="audit:us3:t103:action-session"
        ),
        build_case_terminal_event(
            hold_terminal, audit_reference="audit:us3:t103:action-fulfillment"
        ),
    ):
        outbox.append(event)


@pytest.mark.integration
def test_us3_t103_vertical_slice_gate_is_safe_and_replay_labeled() -> None:
    policy = _policy()
    context, analysis_request = _proposal_context()
    validator = ProposalValidator()
    session_proposal = _proposal(
        ActionType.REVOKE_SUSPICIOUS_SESSION,
        "session-us3-t103",
        "timeline-session-us3",
        "proposal-session-us3-t103",
    )
    hold_proposal = _proposal(
        ActionType.HOLD_FULFILLMENT,
        "fulfillment-us3-t103",
        "timeline-fulfillment-us3",
        "proposal-fulfillment-us3-t103",
    )
    session_validation = validator.validate(session_proposal, context)
    hold_validation = validator.validate(hold_proposal, context)
    assert session_validation.status is ProposalValidationStatus.VALID
    assert hold_validation.status is ProposalValidationStatus.VALID
    assert session_validation.policy_evaluation_ready is True
    assert hold_validation.policy_evaluation_ready is True
    assert session_validation.replay_live_mode == "replay"
    assert hold_validation.replay_live_mode == "replay"
    assert session_validation.canonical_action_identity
    assert hold_validation.canonical_action_identity
    assert analysis_request.provider_mode is ProviderMode.REPLAY
    assert analysis_request.replay_label is ProviderMode.REPLAY
    assert set(analysis_request.allowed_tools).isdisjoint(
        {"execute_payment", "refund", "cancel", "database_write", "shell", "network"}
    )

    allow = _decision(policy, session_proposal)
    hold_allow = _decision(policy, hold_proposal)
    refund = TypedActionProposal(
        tenant_id=TENANT,
        correlation_id=CORRELATION,
        proposal_id="proposal-refund-us3-t103",
        case_id=CASE,
        action_type=ActionType.REFUND_PAYMENT,
        target_resource="payment-us3-t103",
        parameters={"reason": "approval-bound replay review"},
        rationale="Captured payment refund requires independent approval.",
        evidence_references=(EVIDENCE[1],),
        attribution_references=("timeline-payment-us3",),
        requested_amount_minor=8_000,
        currency="INR",
        idempotency_key="supplied-refund-us3-t103",
        analysis_id=ANALYSIS,
    )
    refund_policy_decision = evaluate_policy(
        policy_version=policy,
        tenant_id=TENANT,
        case_id=CASE,
        proposal_id=refund.proposal_id,
        correlation_id=CORRELATION,
        action=refund.action_type.value,
        confidence=0.99,
        resource={
            "resource_id": refund.target_resource,
            "connector_id": "razorpay-test",
            "state": "captured",
        },
        amount_minor=refund.requested_amount_minor,
        currency=refund.currency,
        is_reversible=True,
        customer_impact={"class": "high"},
        evaluated_at=NOW,
    )
    low_confidence = evaluate_policy(
        policy_version=policy,
        tenant_id=TENANT,
        case_id=CASE,
        proposal_id="proposal-low-confidence-us3-t103",
        correlation_id=CORRELATION,
        action=ActionType.HOLD_FULFILLMENT.value,
        confidence=0.80,
        resource=_resource(hold_proposal),
        amount_minor=0,
        is_reversible=True,
        customer_impact={"class": "low"},
        evaluated_at=NOW,
    )
    cross_tenant = evaluate_policy(
        policy_version=policy,
        tenant_id="tenant-other-us3-t103",
        case_id=CASE,
        proposal_id="proposal-cross-tenant-us3-t103",
        correlation_id=CORRELATION,
        action=ActionType.REVOKE_SUSPICIOUS_SESSION.value,
        confidence=0.99,
        resource=_resource(session_proposal),
        amount_minor=0,
        is_reversible=True,
        customer_impact={"class": "low"},
        evaluated_at=NOW,
    )
    assert allow.result is PolicyResult.ALLOW
    assert hold_allow.result is PolicyResult.ALLOW
    assert refund_policy_decision.result is PolicyResult.APPROVAL_REQUIRED
    assert low_confidence.result is PolicyResult.DENY
    assert cross_tenant.result is PolicyResult.ESCALATE
    assert allow.evaluated_conditions["policy_version"] == POLICY_ID
    assert allow.evaluated_conditions["policy_checksum"] == policy.checksum

    model_policy_change = validate_tenant_policy_configuration(
        tenant_id=TENANT,
        change="model-attempted-threshold-change",
        thresholds={"min_confidence": 0.95},
        actor_role="model",
    )
    assert model_policy_change.accepted is False
    assert model_policy_change.audit_reference.startswith("policy-change:")

    approval_service = ApprovalService()
    approval_request = approval_service.request_approval(
        tenant_id=TENANT,
        case_id=CASE,
        proposal_id=refund.proposal_id,
        action_type=refund.action_type.value,
        target_resource=refund.target_resource,
        proposer_id=ANALYSIS,
        policy_version_id=POLICY_ID,
        correlation_id=CORRELATION,
        requested_at=NOW,
        request_id="approval-request-refund-us3-t103",
    )
    with pytest.raises(ApprovalError, match="distinct"):
        approval_service.approve(
            approval_request,
            approver_context=_context(ANALYSIS, "approver"),
            approved_at=NOW,
        )
    approval = approval_service.approve(
        approval_request,
        approver_context=_context("approver-us3-t103", "approver"),
        approved_at=NOW,
        approval_id="approval-refund-us3-t103",
    )
    authorized = approval_service.authorize_action(
        proposal={
            "tenant_id": TENANT,
            "case_id": CASE,
            "proposal_id": refund.proposal_id,
            "action_type": refund.action_type.value,
            "target_resource": refund.target_resource,
            "policy_version_id": POLICY_ID,
            "proposer_id": ANALYSIS,
        },
        approval=approval,
        approver_context=_context("approver-us3-t103", "approver"),
        now=NOW,
    )
    assert authorized.execution_authorized is True

    payments = (
        {
            "tenant_id": TENANT,
            "case_id": CASE,
            "payment_id": "payment-malicious-us3-t103",
            "timeline_event_id": "timeline-payment-us3",
            "evidence_references": (EVIDENCE[1],),
            "state": "captured",
            "amount_minor": 50_000,
            "currency": "INR",
            "payment_source": "merchant-ledger",
            "attribution_label": "malicious",
            "contained_minor": 20_000,
        },
        {
            "tenant_id": TENANT,
            "case_id": CASE,
            "payment_id": "payment-legitimate-us3-t103",
            "timeline_event_id": "timeline-legitimate-us3",
            "evidence_references": (EVIDENCE[0],),
            "state": "captured",
            "amount_minor": 2_499,
            "currency": "INR",
            "payment_source": "merchant-ledger",
            "attribution_label": "legitimate",
            "legitimate_value_disrupted_minor": 2_499,
        },
    )
    exposure = calculate_exposure(
        tenant_id=TENANT,
        case_id=CASE,
        payments=payments,
        calculation_version="exposure-us3-t103-v1",
        currency="INR",
    )
    assert exposure.gross_exposure_minor == 50_000
    assert exposure.contained_value_minor == 20_000
    assert exposure.legitimate_value_disrupted_minor == 2_499
    assert exposure.remaining_exposure_minor == 30_000
    assert exposure.currency == "INR"

    session_simulator = RecordingSimulator(
        DeterministicActionSimulator.for_operation(
            TENANT,
            "revoke_suspicious_session",
            scenario=ActionSimulatorScenario.UNKNOWN,
            resource_states={"session-us3-t103": "active"},
        )
    )
    hold_simulator = RecordingSimulator(
        DeterministicActionSimulator.for_operation(
            TENANT,
            "hold_fulfillment",
            scenario=ActionSimulatorScenario.COMPLETED,
            resource_states={"fulfillment-us3-t103": "ready"},
        )
    )
    store = InMemoryActionExecutionStore()
    gateway = ActionGateway(
        connectors={
            "session-actions": session_simulator,
            "fulfillment-actions": hold_simulator,
        },
        execution_store=store,
    )
    reviewer_context = _context("reviewer-us3", "reviewer")
    service_context = _context(
        "action-gateway-us3", "service", identity_type=IdentityType.SERVICE
    )
    session_request = _request(
        session_proposal,
        canonical_action_id=session_validation.canonical_action_identity,
        decision_id=allow.decision_id,
        checksum="checksum-session-us3-t103",
    )
    duplicate_proposal = session_proposal.model_copy(
        update={
            "proposal_id": "proposal-session-us3-t103-duplicate",
            "analysis_id": "analysis-us3-t103-duplicate",
            "idempotency_key": "supplied-duplicate-provenance",
        }
    )
    duplicate_request = _request(
        duplicate_proposal,
        canonical_action_id=session_validation.canonical_action_identity,
        decision_id=allow.decision_id,
        checksum="checksum-session-us3-t103",
    )
    duplicate_decision = allow.model_copy(
        update={"proposal_id": duplicate_proposal.proposal_id}
    )
    recovery_probe = ReconciliationProbe()
    merchant_verifier = ReplayMerchantState(
        {"session-us3-t103": "revoked", "fulfillment-us3-t103": "unknown"}
    )
    session_pipeline_result, session_response, session_route = _run_session_pipeline(
        gateway=gateway,
        store=store,
        request=session_request,
        duplicate_request=duplicate_request,
        decision=allow,
        duplicate_decision=duplicate_decision,
        session_proposal=session_proposal,
        canonical_action_id=session_validation.canonical_action_identity,
        reviewer_context=reviewer_context,
        service_context=service_context,
        verifier=merchant_verifier,
        recovery_probe=recovery_probe,
    )
    assert session_pipeline_result["terminal_state"] == "verified_contained"
    assert session_simulator.calls == 1
    assert session_simulator.remote_effects == 1
    duplicate_effect_count = session_simulator.remote_effects - 1
    assert duplicate_effect_count == 0
    assert session_route.verification.verification_method == "merchant_state_read"
    assert session_route.verification.verification_version == "verification-v1.0.0"
    assert session_route.verification.state_checksum

    unauthorized_command = CaseWorkflowCommand(
        tenant_id=TENANT,
        case_id=CASE,
        correlation_id=CORRELATION,
        command_id="command-unauthorized-us3-t103",
        expected_state="containing",
        stages=("run_containment",),
        metadata={"mode": "replay", "label": "replay"},
    )
    with pytest.raises(ContainmentActivityError, match="service identity"):
        run_containment(
            unauthorized_command,
            runner=lambda _command: {"tenant_id": TENANT, "case_id": CASE},
            authorization_context=reviewer_context,
        )
    assert session_simulator.calls == 1

    hold_request = _request(
        hold_proposal,
        canonical_action_id=hold_validation.canonical_action_identity,
        decision_id=hold_allow.decision_id,
        checksum="checksum-hold-us3-t103",
    )
    hold_pipeline_result, hold_response, hold_route = _run_hold_pipeline(
        gateway=gateway,
        store=store,
        request=hold_request,
        decision=hold_allow,
        proposal=hold_proposal,
        canonical_action_id=hold_validation.canonical_action_identity,
        service_context=service_context,
        verifier=merchant_verifier,
        exposure=exposure,
    )
    assert hold_pipeline_result["terminal_state"] == "escalated_unresolved"
    assert hold_route.verification.result is VerificationResult.INCONCLUSIVE
    assert hold_route.escalation.owner_id == "escalation-owner-us3"
    assert hold_simulator.calls == 1
    assert hold_simulator.remote_effects == 1

    forbidden_execution_count = 0
    with pytest.raises(ActionGatewayError):
        gateway.submit(
            session_request,
            policy_decision=allow,
            authoritative_resource=_resource(session_proposal),
            authorization_context=reviewer_context,
        )
    forbidden_execution_count += 1
    with pytest.raises(ControlPlaneError, match="service identity"):
        submit_action(
            request=hold_request,
            gateway=gateway,
            policy_decision=hold_allow,
            authoritative_resource=_resource(hold_proposal),
            authorization_context=reviewer_context,
            canonical_action_id=hold_validation.canonical_action_identity,
            execution_store=store,
        )
    forbidden_execution_count += 1
    refund_request = ActionGatewayRequest(
        tenant_id=TENANT,
        correlation_id=CORRELATION,
        case_id=CASE,
        proposal_id=refund.proposal_id,
        action_type=ActionType.REFUND_PAYMENT,
        connector_id="razorpay-test",
        operation="refund_payment",
        target_resource=refund.target_resource,
        parameters={"requested_amount_minor": "8000", "currency": "INR"},
        policy_decision_id=refund_policy_decision.decision_id,
        policy_version_id=POLICY_ID,
        idempotency_key="refund-gateway-key-us3-t103",
        causation_id=refund.proposal_id,
        request_checksum="checksum-refund-us3-t103",
        requested_at=NOW,
    )
    with pytest.raises(ActionGatewayError, match="approval|required|unsupported"):
        gateway.submit(
            refund_request,
            policy_decision=refund_policy_decision,
            authoritative_resource={
                "tenant_id": TENANT,
                "case_id": CASE,
                "resource_id": refund.target_resource,
                "resource_type": "payments",
                "connector_id": "razorpay-test",
                "state": "captured",
            },
            authorization_context=service_context,
        )
    forbidden_execution_count += 1
    assert forbidden_execution_count == 3
    assert session_simulator.calls == 1
    assert hold_simulator.calls == 1
    assert set(gateway.connector_ids) == {"session-actions", "fulfillment-actions"}
    assert Settings(_env_file=None).live_actions_enabled is False
    assert Settings(_env_file=None).live_financial_actions_enabled is False
    assert (
        TenantConfiguration(
            tenant_id=TENANT,
            connector_ids=frozenset(gateway.connector_ids),
            policy_version_id=POLICY_ID,
        ).live_financial_actions_enabled
        is False
    )

    with pytest.raises(TerminalStateError, match="generic terminal aliases"):
        transition_case(
            current_state="containing",
            requested_state="closed",
            tenant_id=TENANT,
            case_id=CASE,
        )
    session_terminal = (
        session_pipeline_result["terminal_transition"]
        if "terminal_transition" in session_pipeline_result
        else transition_case(
            current_state="containing",
            requested_state="verified_contained",
            tenant_id=TENANT,
            case_id=CASE,
            action_id=session_response.idempotency_key,
            execution_id=session_route.verification.execution_id,
            verification_id=session_route.verification.verification_id,
            verification_result=session_route.verification.result.value,
            required_actions_completed=True,
            unresolved=False,
        )
    )
    hold_terminal = (
        hold_pipeline_result["terminal_transition"]
        if "terminal_transition" in hold_pipeline_result
        else transition_case(
            current_state="containing",
            requested_state="escalated_unresolved",
            tenant_id=TENANT,
            case_id=CASE,
            action_id=hold_response.idempotency_key,
            execution_id=hold_route.verification.execution_id,
            verification_id=hold_route.verification.verification_id,
            escalation_id=hold_route.escalation.escalation_id,
            verification_result=hold_route.verification.result.value,
            unresolved=True,
            remaining_exposure_minor=exposure.remaining_exposure_minor,
            currency=exposure.currency,
        )
    )

    audits = InMemoryAuditRepository()
    _append_audit_trace(
        audits,
        session_proposal=session_proposal,
        hold_proposal=hold_proposal,
        policy=policy,
        approval=approval,
        session_response=session_response,
        session_route=session_route,
        hold_response=hold_response,
        hold_route=hold_route,
        exposure=exposure,
    )
    assert len(audits.records) == 14
    previous = None
    for record in audits.records:
        assert record.tenant_id == TENANT
        assert record.case_id == CASE
        assert record.record_checksum != "pending"
        assert record.previous_record_checksum == previous
        previous = record.record_checksum
    assert {record.action.rsplit(".", 1)[-1] for record in audits.records} >= {
        "incident",
        "evidence",
        "attribution",
        "exposure",
        "proposal",
        "policy",
        "approval",
        "canonical_action",
        "execution",
        "verification",
        "escalation",
        "terminal",
    }

    outbox = InMemoryOutbox()
    _append_outbox_trace(
        outbox,
        policy_decision=allow,
        approval=approval,
        session_request=session_request,
        session_response=session_response,
        recovery=recover_action(
            request=session_request,
            remote=recovery_probe,
            store=store,
            duplicate_deliveries=3,
        ),
        session_verification=session_route.verification,
        hold_request=hold_request,
        hold_response=hold_response,
        hold_verification=hold_route.verification,
        escalation=hold_route.escalation,
        session_terminal=session_terminal,
        hold_terminal=hold_terminal,
    )
    assert len(outbox.events) == 10
    serialized = json.dumps(
        {
            "audit": [record.model_dump(mode="json") for record in audits.records],
            "outbox": [
                event.model_dump(mode="json") for event in outbox.events.values()
            ],
        },
        sort_keys=True,
    ).lower()
    for forbidden in (
        "secret",
        "credential",
        "password",
        "raw",
        "email",
        "phone",
        "pii",
    ):
        assert forbidden not in serialized
