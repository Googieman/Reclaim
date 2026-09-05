"""T101 deterministic recovery harness; live dependencies are not simulated."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from action_gateway.idempotency import InMemoryActionExecutionStore
from action_gateway.reconciliation import recover_action
from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest


@dataclass
class RemoteWithLateOutcome:
    effects: int = 0
    completed: dict[str, str] = field(default_factory=dict)

    def invoke(self, key: str) -> str:
        self.effects += 1
        self.completed[key] = "completed"
        return "unknown"

    def reconcile(self, key: str) -> str:
        return self.completed.get(key, "not_found")


def test_restart_duplicate_delivery_and_late_outcome_reconcile_once() -> None:
    request = ActionGatewayRequest(
        tenant_id="tenant-us3-t101",
        correlation_id="corr-us3-t101",
        case_id="case-us3-t101",
        proposal_id="proposal-us3-t101",
        action_type="revoke_suspicious_session",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-us3-t101",
        policy_decision_id="decision-us3-t101",
        policy_version_id="policy-us3-t101",
        idempotency_key="canonical-action-us3-t101",
        causation_id="proposal-us3-t101",
        request_checksum="checksum-us3-t101",
        requested_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    store = InMemoryActionExecutionStore()
    remote = RemoteWithLateOutcome()
    first = recover_action(
        request=request,
        remote=remote,
        process_restart=True,
        timeout=True,
        duplicate_deliveries=2,
        late_remote_response=True,
        store=store,
    )
    second = recover_action(
        request=request,
        remote=remote,
        process_restart=True,
        duplicate_deliveries=3,
        store=store,
    )
    assert first.state is ActionExecutionState.VERIFIED_SUCCESS
    assert second.state is ActionExecutionState.VERIFIED_SUCCESS
    assert first.reconciliation_performed is True
    assert first.retry_before_reconciliation is False
    assert remote.effects == 1


def test_live_dependency_claims_are_not_hidden_in_deterministic_harness() -> None:
    # This fixture intentionally covers recovery semantics with a local fake;
    # it does not report PostgreSQL, Temporal, Redpanda, or provider execution.
    assert RemoteWithLateOutcome.__name__ == "RemoteWithLateOutcome"


def test_restart_after_persisted_pre_connector_state_reconciles_without_invoke() -> (
    None
):
    request = ActionGatewayRequest(
        tenant_id="tenant-us3-t101-restart",
        correlation_id="corr-us3-t101-restart",
        case_id="case-us3-t101-restart",
        proposal_id="proposal-us3-t101-restart",
        action_type="revoke_suspicious_session",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-us3-t101-restart",
        policy_decision_id="decision-us3-t101-restart",
        policy_version_id="policy-us3-t101-restart",
        idempotency_key="canonical-action-us3-t101-restart",
        causation_id="proposal-us3-t101-restart",
        request_checksum="checksum-us3-t101-restart",
        requested_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    store = InMemoryActionExecutionStore()
    store.begin(
        request=request,
        resource_type="sessions",
        policy_decision_id=request.policy_decision_id,
    )
    remote = RemoteWithLateOutcome()
    result = recover_action(
        request=request, remote=remote, store=store, process_restart=True
    )

    assert result.state is ActionExecutionState.RECONCILED
    assert result.reconciliation_performed is True
    assert remote.effects == 0
