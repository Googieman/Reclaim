"""T084 idempotency and failure-recovery tests with deterministic fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import pytest

from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest
from us3_test_seams import require_symbol


@dataclass
class DeterministicRemote:
    """A local remote fake where UNKNOWN means the effect may already have happened."""

    outcomes: list[str]
    effects: int = 0
    _completed: dict[str, str] = field(default_factory=dict)
    _responses: dict[str, str] = field(default_factory=dict)

    def invoke(self, idempotency_key: str) -> str:
        if idempotency_key in self._responses:
            return self._responses[idempotency_key]
        outcome = self.outcomes.pop(0)
        self._responses[idempotency_key] = outcome
        if outcome in {"completed", "unknown"}:
            self.effects += 1
            self._completed[idempotency_key] = "completed"
        return outcome

    def reconcile(self, idempotency_key: str) -> str:
        return self._completed.get(idempotency_key, "not_found")


def _request() -> ActionGatewayRequest:
    return ActionGatewayRequest(
        tenant_id="tenant-us3-recovery",
        correlation_id="corr-us3-recovery-001",
        case_id="case-us3-recovery-001",
        proposal_id="proposal-us3-recovery-001",
        action_type="revoke_suspicious_session",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-us3-recovery-001",
        policy_decision_id="decision-us3-recovery-001",
        policy_version_id="policy-us3-v1.0.0",
        idempotency_key="canonical-action-us3-recovery-001",
        causation_id="proposal-us3-recovery-001",
        request_checksum="sha256:request-us3-recovery-001",
        requested_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )


def test_deterministic_remote_reconciles_unknown_without_duplicate_effect() -> None:
    remote = DeterministicRemote(outcomes=["unknown"])
    key = "canonical-action-us3-recovery-001"

    assert remote.invoke(key) == "unknown"
    assert remote.effects == 1
    assert remote.reconcile(key) == "completed"
    assert remote.invoke(key) == "unknown"
    assert remote.effects == 1


def test_recovery_fixture_contains_restart_timeout_late_response_and_duplicate_delivery() -> (
    None
):
    request = _request()
    failure_events = (
        "process_restart_before_persist",
        "timeout_after_remote_submission",
        "unknown_remote_result",
        "late_remote_response",
        "duplicate_event_delivery",
    )

    assert request.idempotency_key == "canonical-action-us3-recovery-001"
    assert len(failure_events) == 5
    assert len(set(failure_events)) == len(failure_events)


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owner T095/T101: durable idempotency and recovery implementation is absent",
)
def test_gateway_recovery_reconciles_before_retry_after_restart_and_timeout() -> None:
    recover = require_symbol(
        "action_gateway.reconciliation",
        "recover_action",
        task="T084 -> T095/T101",
    )
    remote = DeterministicRemote(outcomes=["unknown", "completed"])
    result = recover(
        request=_request(),
        remote=remote,
        process_restart=True,
        timeout=True,
        duplicate_deliveries=2,
        late_remote_response=True,
    )

    assert result.state is ActionExecutionState.VERIFIED_SUCCESS
    assert remote.effects == 1
    assert result.reconciliation_performed is True
    assert result.retry_before_reconciliation is False
