"""Live worker, API, and Redis restart recovery scenarios for T153."""

from __future__ import annotations

import time
from typing import Any

from support.t153_runtime import (
    ALLOWLISTED_FAILURE_CODES,
    TERMINAL_ORCHESTRATION_STATES,
    DurableSnapshot,
    T153Config,
    intake_payload,
    post_intake,
    postgres_snapshot,
    raw_report_reference,
    record_recovery_observation,
    redis_queue_state,
    restart_t153_service,
    unique_marker,
    verify_minio_raw_report,
    wait_for_condition,
    wait_for_terminal_case,
)


def _terminal_status(case: dict[str, Any]) -> str:
    orchestration = case.get("orchestration") or {}
    status = str(orchestration.get("status", ""))
    assert status in TERMINAL_ORCHESTRATION_STATES
    if status == "requires_attention":
        assert orchestration.get("failure_code") in ALLOWLISTED_FAILURE_CODES
    assert orchestration.get("workflow_version") == "incident-analysis-handoff.v1"
    return status


def _assert_exact_snapshot(snapshot: DurableSnapshot, terminal_status: str) -> None:
    assert snapshot.incidents == 1
    assert snapshot.cases == 1
    assert snapshot.accepted_outbox == 1
    assert snapshot.published_outbox == 1
    assert snapshot.orchestration_runs == 1
    assert snapshot.stage_attempts == (3 if terminal_status == "awaiting_human" else 2)
    assert snapshot.duplicate_stage_keys == 0
    assert snapshot.intake_audits == 1
    assert snapshot.timeline_events == 1
    assert snapshot.model_runs == (1 if terminal_status == "awaiting_human" else 0)
    assert snapshot.action_executions == 0


def _wait_for_queue(config: T153Config) -> dict[str, Any]:
    def queued() -> dict[str, Any] | None:
        state = redis_queue_state(config)
        return state if state["queue_depth"] > 0 else None

    return wait_for_condition(queued, timeout_seconds=45.0, poll_seconds=1.0)


def _wait_for_reloaded_redis(config: T153Config) -> dict[str, Any]:
    def reloaded() -> dict[str, Any] | None:
        state = redis_queue_state(config)
        return (
            state
            if state["aof_enabled"] and state["aof_last_load_status"] == "ok"
            else None
        )

    return wait_for_condition(reloaded, timeout_seconds=45.0, poll_seconds=1.0)


def _signature(case: dict[str, Any]) -> tuple[Any, ...]:
    orchestration = case.get("orchestration") or {}
    return tuple(
        orchestration.get(field)
        for field in (
            "run_id",
            "external_execution_id",
            "stage",
            "status",
            "failure_code",
            "workflow_version",
        )
    )


def test_t153_worker_restart_recovers_queued_case(t153_config: T153Config) -> None:
    marker = unique_marker("worker-restart")
    restart_t153_service(t153_config, "n8n-worker", "stop")
    try:
        accepted = post_intake(t153_config, marker, payload=intake_payload(marker))
        assert accepted["status"] == "accepted"
        relay_snapshot = wait_for_condition(
            lambda: (
                snapshot
                if (snapshot := postgres_snapshot(t153_config, marker)).published_outbox == 1
                else None
            ),
            timeout_seconds=60.0,
            poll_seconds=1.0,
        )
        before = postgres_snapshot(t153_config, marker)
        queue_before = _wait_for_queue(t153_config)
        assert before.orchestration_runs == 0
        started = time.monotonic()
        restart_t153_service(t153_config, "n8n-worker", "start")
        terminal = wait_for_terminal_case(t153_config, marker)
        elapsed = time.monotonic() - started
        status = _terminal_status(terminal)
        after = postgres_snapshot(t153_config, marker)
        _assert_exact_snapshot(after, status)
        assert relay_snapshot.published_outbox == 1
        assert elapsed > 0
        assert after.incidents == before.incidents == 1
        assert after.cases == before.cases == 1
        assert after.accepted_outbox == before.accepted_outbox == 1
        record_recovery_observation(
            t153_config,
            scenario="worker-restart",
            before=before,
            after=after,
            elapsed_seconds=elapsed,
            metadata={
                "service": "n8n-worker",
                "terminal_status": status,
                "queue_depth_before": queue_before["queue_depth"],
            },
        )
    finally:
        restart_t153_service(t153_config, "n8n-worker", "start")


def test_t153_api_restart_recovers_with_bounded_http_retry(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("api-restart")
    restart_t153_service(t153_config, "n8n-worker", "stop")
    try:
        accepted = post_intake(t153_config, marker, payload=intake_payload(marker))
        assert accepted["status"] == "accepted"
        wait_for_condition(
            lambda: (
                snapshot
                if (snapshot := postgres_snapshot(t153_config, marker)).published_outbox == 1
                else None
            ),
            timeout_seconds=60.0,
            poll_seconds=1.0,
        )
        before = postgres_snapshot(t153_config, marker)
        queue_before = _wait_for_queue(t153_config)
        assert before.orchestration_runs == 0
        restart_t153_service(t153_config, "api", "stop")
        started = time.monotonic()
        restart_t153_service(t153_config, "n8n-worker", "start")
        restart_t153_service(t153_config, "api", "start")
        terminal = wait_for_terminal_case(t153_config, marker)
        elapsed = time.monotonic() - started
        status = _terminal_status(terminal)
        after = postgres_snapshot(t153_config, marker)
        _assert_exact_snapshot(after, status)
        assert elapsed > 0
        record_recovery_observation(
            t153_config,
            scenario="api-restart",
            before=before,
            after=after,
            elapsed_seconds=elapsed,
            metadata={
                "service": "api",
                "terminal_status": status,
                "queue_depth_before": queue_before["queue_depth"],
            },
        )
    finally:
        restart_t153_service(t153_config, "api", "start")
        restart_t153_service(t153_config, "n8n-worker", "start")


def test_t153_redis_restart_preserves_queue_and_authoritative_state(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("redis-restart")
    restart_t153_service(t153_config, "n8n-worker", "stop")
    try:
        accepted = post_intake(t153_config, marker, payload=intake_payload(marker))
        assert accepted["status"] == "accepted"
        wait_for_condition(
            lambda: (
                snapshot
                if (snapshot := postgres_snapshot(t153_config, marker)).published_outbox == 1
                else None
            ),
            timeout_seconds=60.0,
            poll_seconds=1.0,
        )
        before = postgres_snapshot(t153_config, marker)
        queue_before = _wait_for_queue(t153_config)
        started = time.monotonic()
        restart_t153_service(t153_config, "redis", "restart")
        queue_after = _wait_for_reloaded_redis(t153_config)
        restart_t153_service(t153_config, "n8n-worker", "start")
        terminal = wait_for_terminal_case(t153_config, marker)
        elapsed = time.monotonic() - started
        status = _terminal_status(terminal)
        after = postgres_snapshot(t153_config, marker)
        _assert_exact_snapshot(after, status)
        assert queue_before["queue_depth"] > 0
        assert queue_after["aof_enabled"] is True
        assert queue_after["aof_last_load_status"] == "ok"
        assert after.incidents == before.incidents == 1
        assert after.cases == before.cases == 1
        assert after.accepted_outbox == before.accepted_outbox == 1
        assert after.published_outbox == before.published_outbox == 1
        assert elapsed > 0
        record_recovery_observation(
            t153_config,
            scenario="redis-restart",
            before=before,
            after=after,
            elapsed_seconds=elapsed,
            metadata={
                "service": "redis",
                "terminal_status": status,
                "queue_depth_before": queue_before["queue_depth"],
                "queue_depth_after": queue_after["queue_depth"],
                "aof_last_load_status": queue_after["aof_last_load_status"],
            },
        )
    finally:
        restart_t153_service(t153_config, "redis", "start")
        restart_t153_service(t153_config, "n8n-worker", "start")


def test_t153_terminal_case_is_unchanged_by_allowed_service_restarts(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("terminal-control")
    accepted = post_intake(t153_config, marker, payload=intake_payload(marker))
    assert accepted["status"] == "accepted"
    terminal = wait_for_terminal_case(t153_config, marker)
    status = _terminal_status(terminal)
    before = postgres_snapshot(t153_config, marker)
    before_signature = _signature(terminal)
    before_reference = raw_report_reference(t153_config, marker)
    before_object = verify_minio_raw_report(t153_config, marker)
    started = time.monotonic()
    try:
        for service in ("n8n-worker", "api", "redis"):
            restart_t153_service(t153_config, service, "restart")
        after_terminal = wait_for_terminal_case(t153_config, marker)
        after = postgres_snapshot(t153_config, marker)
        elapsed = time.monotonic() - started
    finally:
        restart_t153_service(t153_config, "api", "start")
        restart_t153_service(t153_config, "redis", "start")
        restart_t153_service(t153_config, "n8n-worker", "start")
    assert _terminal_status(after_terminal) == status
    assert _signature(after_terminal) == before_signature
    assert after == before
    after_reference = raw_report_reference(t153_config, marker)
    after_object = verify_minio_raw_report(t153_config, marker)
    assert after_reference["checksum"] == before_reference["checksum"]
    assert after_object["checksum"] == before_object["checksum"]
    assert elapsed > 0
    record_recovery_observation(
        t153_config,
        scenario="terminal-control",
        before=before,
        after=after,
        elapsed_seconds=elapsed,
        metadata={"service": "n8n-worker-api-redis", "terminal_status": status},
    )
