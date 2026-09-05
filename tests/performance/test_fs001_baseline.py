"""Measured local FS-001 intake, replay, and recovery baseline.

These are callable-level measurements over the deterministic/in-memory harness;
they are not production SLO evidence and do not measure external services.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.tests.integration.test_intake_service import (
    MemoryState,
    authorization_context,
    intake_request,
    make_service,
)
from evaluation.performance import compare_provisional_targets, measure_performance
from action_gateway.idempotency import InMemoryActionExecutionStore
from action_gateway.reconciliation import recover_action
from packages.contracts.action_gateway import ActionGatewayRequest
from packages.contracts.analysis_policy import ActionType
from replay.runner import ReplayRunner

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/canonical/incident.json"


class _PerformanceRemote:
    def __init__(self, invoke_result: str, reconcile_result: str) -> None:
        self.invoke_result = invoke_result
        self.reconcile_result = reconcile_result

    def invoke(self, _key: str) -> str:
        return self.invoke_result

    def reconcile(self, _key: str) -> str:
        return self.reconcile_result


def _environment() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "runner": "pytest-local-inmemory-deterministic",
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "dataset_cases": 1,
        "external_services": False,
        "warm_measurements": True,
        "repetitions": {"intake": 25, "replay": 10, "recovery": 1},
    }


def test_fs001_local_intake_replay_and_recovery_baseline(record_property: Any) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    state = MemoryState()
    intake_service = make_service(state)
    request = intake_request(tenant_id="tenant-a", idempotency_key="baseline-intake-1")
    context = authorization_context("tenant-a")

    def intake() -> object:
        return intake_service.accept(request, authorization_context=context)

    runner = ReplayRunner()

    def replay() -> dict[str, Any]:
        return runner.run(
            fixture=fixture,
            tenant_id=fixture["tenant_id"],
            case_id=fixture["case_id"],
            deterministic_seed=fixture["deterministic_seed"],
            mode="replay",
        )

    def recovery() -> object:
        store = InMemoryActionExecutionStore()
        return recover_action(
            request=_recovery_request(),
            remote=_PerformanceRemote("unknown", "not_found"),
            store=store,
        )

    intake_measurement = measure_performance(
        intake,
        iterations=25,
        warmup_iterations=3,
        environment=_environment(),
        qualification="local-inmemory-simulator",
    )
    replay_measurement = measure_performance(
        replay,
        iterations=10,
        warmup_iterations=2,
        environment=_environment(),
        qualification="local-deterministic-replay",
    )
    recovery_measurement = measure_performance(
        lambda: recover_action(
            request=_recovery_request(),
            remote=_PerformanceRemote("completed", "completed"),
            store=InMemoryActionExecutionStore(),
        ),
        iterations=1,
        warmup_iterations=0,
        recovery_operation=recovery,
        environment=_environment(),
        qualification="local-action-recovery-simulator",
    )

    for name, measurement in {
        "intake": intake_measurement,
        "replay": replay_measurement,
        "recovery": recovery_measurement,
    }.items():
        assert measurement["measured"] is True
        assert measurement["failure_count"] == 0, name
        assert measurement["failure_rate"] == 0
        assert measurement["p95_latency_ms"] is not None, name
        record_property(f"{name}_measurement", json.dumps(measurement, sort_keys=True))

    assert intake_measurement["sample_size"] == 25
    assert replay_measurement["sample_size"] == 10
    assert recovery_measurement["recovery_time_ms"] is not None
    assert recovery_measurement["recovery_failure"] is False
    assert replay()["mode"] == "replay"
    assert replay()["side_effects"] is False

    comparison = {
        "intake": compare_provisional_targets(intake_measurement),
        "replay": compare_provisional_targets(replay_measurement),
    }
    record_property(
        "provisional_target_comparison", json.dumps(comparison, sort_keys=True)
    )
    print(
        json.dumps(
            {
                "intake": intake_measurement,
                "replay": replay_measurement,
                "recovery": recovery_measurement,
            },
            sort_keys=True,
        )
    )


def _recovery_request() -> Any:
    return ActionGatewayRequest(
        tenant_id="tenant-a",
        correlation_id="corr-performance",
        case_id="case-performance",
        proposal_id="proposal-performance",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-performance",
        parameters={"reason": "performance"},
        policy_decision_id="policy-performance",
        policy_version_id="policy-v1.0.0",
        idempotency_key="performance-recovery",
        causation_id="proposal-performance",
        request_checksum="sha256:performance",
        requested_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    )
