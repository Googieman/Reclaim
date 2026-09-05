"""Fresh-volume and duplicate-delivery acceptance tests for T153.

These tests are intentionally environment-gated.  They never turn missing
services into an in-memory success and never print the synthetic narrative.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from support.t153_runtime import (
    ALLOWLISTED_FAILURE_CODES,
    DOMAIN_TOPIC,
    TERMINAL_ORCHESTRATION_STATES,
    DurableSnapshot,
    T153Config,
    assert_schema_contract,
    authoritative_outbox_event,
    compose_service_statuses,
    intake_payload,
    n8n_execution_count,
    post_intake,
    postgres_snapshot,
    readiness,
    raw_report_reference,
    republish_authoritative_event,
    require_n8n_execution_observation,
    unique_marker,
    verify_minio_raw_report,
    wait_for_condition,
    wait_for_terminal_case,
    web_cases_response,
)

REQUIRED_SERVICES = frozenset(
    {"postgres", "redpanda", "redis", "minio", "api", "web", "event-relay", "n8n-main", "n8n-worker"}
)
REVIEWER_AUTHORIZATION = "Bearer demo-reviewer"
REJECTED_COMPOSE_PROJECT = "reclaim-demo"
T153_ACCEPTANCE_FIELDS = (
    "reported_amount_minor",
    "reported_currency",
    "raw_input_reference",
)
T153_FAILURE_CODES = ("model_unavailable", "policy_failed")


def _wait_for_relay(config: T153Config, marker: str) -> DurableSnapshot:
    def ready() -> DurableSnapshot | None:
        snapshot = postgres_snapshot(config, marker)
        if (
            snapshot.incidents == 1
            and snapshot.cases == 1
            and snapshot.accepted_outbox == 1
            and snapshot.published_outbox == 1
        ):
            return snapshot
        return None

    return wait_for_condition(ready, timeout_seconds=60.0, poll_seconds=1.0)


def _assert_snapshot_is_authoritative(
    snapshot: DurableSnapshot, terminal_status: str
) -> None:
    """Require the exact stage shape for the observed typed terminal outcome."""

    expected_stage_attempts = 3 if terminal_status == "awaiting_human" else 2
    expected_model_runs = 1 if terminal_status == "awaiting_human" else 0
    assert snapshot.incidents == 1
    assert snapshot.cases == 1
    assert snapshot.accepted_outbox == 1
    assert snapshot.published_outbox == 1
    assert snapshot.orchestration_runs == 1
    assert snapshot.stage_attempts == expected_stage_attempts
    assert snapshot.duplicate_stage_keys == 0
    assert snapshot.intake_audits == 1
    assert snapshot.timeline_events == 1
    assert snapshot.model_runs == expected_model_runs
    assert snapshot.action_executions == 0


def _assert_terminal_case(case: dict[str, Any]) -> None:
    orchestration = case.get("orchestration") or {}
    assert orchestration.get("status") in TERMINAL_ORCHESTRATION_STATES
    if orchestration["status"] == "requires_attention":
        assert orchestration.get("failure_code") in ALLOWLISTED_FAILURE_CODES
    assert orchestration.get("workflow_version") == "incident-analysis-handoff.v1"


def test_t153_fresh_schema_health_and_safe_runtime(t153_config: T153Config) -> None:
    assert_schema_contract(t153_config)
    readiness_body = readiness(t153_config)
    assert readiness_body["mode"] == "live"
    assert readiness_body["live_actions_enabled"] is False
    assert readiness_body["live_financial_actions_enabled"] is False

    statuses = compose_service_statuses(t153_config)
    assert set(statuses) == REQUIRED_SERVICES
    assert all(status["state"] == "running" for status in statuses.values())
    assert all(
        status["health"] in {"healthy", ""} for status in statuses.values()
    )
    assert "workflow-worker" not in statuses
    assert "temporal" not in statuses
    web_cases_response(t153_config, unique_marker("web-health"))


def test_t153_acceptance_persists_exact_authoritative_intake_and_terminal_state(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("accepted")
    payload = intake_payload(marker)
    accepted = post_intake(t153_config, marker, payload=payload)
    assert accepted["status"] == "accepted"
    assert accepted["incident_id"] and accepted["case_id"]

    relay_snapshot = _wait_for_relay(t153_config, marker)
    terminal = wait_for_terminal_case(t153_config, marker)
    _assert_terminal_case(terminal)
    final_snapshot = postgres_snapshot(t153_config, marker)
    _assert_snapshot_is_authoritative(
        final_snapshot, (terminal.get("orchestration") or {}).get("status", "")
    )
    assert final_snapshot.published_outbox == relay_snapshot.published_outbox == 1

    reference = raw_report_reference(t153_config, marker)
    assert reference["checksum"].startswith("sha256:")
    assert reference["narrative_checksum"].startswith("sha256:")
    stored = verify_minio_raw_report(t153_config, marker)
    assert stored["checksum"] == reference["checksum"]
    assert stored["size"] > 0

    authoritative = authoritative_outbox_event(t153_config, marker)
    serialized = authoritative.serialized
    assert authoritative.event.event_type.value == "incident.accepted"
    assert authoritative.event.payload["case_id"] == accepted["case_id"]
    assert authoritative.event.payload["narrative_checksum"] == reference["narrative_checksum"]
    assert b"T153 synthetic operator report" not in serialized
    assert b"raw report" not in serialized.lower()
    assert json.dumps(authoritative.event.payload, sort_keys=True).find("narrative") >= 0


def test_t153_duplicate_intake_returns_same_authority_without_new_business_rows(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("duplicate-intake")
    payload = intake_payload(marker)
    accepted = post_intake(t153_config, marker, payload=payload)
    _wait_for_relay(t153_config, marker)
    terminal = wait_for_terminal_case(t153_config, marker)
    before = postgres_snapshot(t153_config, marker)
    _assert_snapshot_is_authoritative(
        before, (terminal.get("orchestration") or {}).get("status", "")
    )

    duplicate = post_intake(t153_config, marker, payload=payload)
    assert duplicate["status"] == "duplicate"
    assert duplicate["incident_id"] == accepted["incident_id"]
    assert duplicate["case_id"] == accepted["case_id"]
    after = postgres_snapshot(t153_config, marker)
    assert after.incidents == before.incidents == 1
    assert after.cases == before.cases == 1
    assert after.accepted_outbox == before.accepted_outbox == 1
    assert after.published_outbox == before.published_outbox == 1
    assert after.orchestration_runs == before.orchestration_runs == 1
    assert after.stage_attempts == before.stage_attempts
    assert after.duplicate_stage_keys == before.duplicate_stage_keys == 0
    assert after.model_runs == before.model_runs
    assert after.action_executions == before.action_executions == 0
    assert after.intake_audits == before.intake_audits + 1


@pytest.mark.asyncio
async def test_t153_duplicate_broker_delivery_reuses_exact_authority(
    t153_config: T153Config,
) -> None:
    marker = unique_marker("duplicate-broker")
    post_intake(t153_config, marker)
    _wait_for_relay(t153_config, marker)
    terminal = wait_for_terminal_case(t153_config, marker)
    before = postgres_snapshot(t153_config, marker)
    _assert_snapshot_is_authoritative(
        before, (terminal.get("orchestration") or {}).get("status", "")
    )
    authoritative_before = authoritative_outbox_event(t153_config, marker)
    execution_before = n8n_execution_count(t153_config, marker)

    authoritative_after = await republish_authoritative_event(t153_config, marker)
    assert authoritative_after.serialized == authoritative_before.serialized
    assert authoritative_after.event.event_id == authoritative_before.event.event_id
    assert authoritative_after.event.payload_checksum == authoritative_before.event.payload_checksum
    assert DOMAIN_TOPIC == "reclaim.domain.v1"

    if execution_before is None:
        require_n8n_execution_observation()

    execution_after = await wait_for_async_count_increase(
        t153_config, marker, execution_before
    )
    assert execution_after > execution_before
    after = postgres_snapshot(t153_config, marker)
    assert after == before
    assert after.orchestration_runs == 1
    assert after.stage_attempts == before.stage_attempts
    assert after.duplicate_stage_keys == before.duplicate_stage_keys == 0
    assert after.model_runs == before.model_runs
    assert after.action_executions == 0


async def wait_for_async_count_increase(
    config: T153Config, marker: str, before: int | None
) -> int:
    if before is None:
        raise AssertionError("n8n execution count was not observable")

    async def read_count() -> int | None:
        return n8n_execution_count(config, marker)

    result = await asyncio.wait_for(
        _poll_async_count(read_count, before), timeout=90.0
    )
    if result is None:
        raise AssertionError("n8n duplicate execution was not observed")
    return result


async def _poll_async_count(
    reader: Any, before: int
) -> int | None:
    deadline = asyncio.get_running_loop().time() + 85.0
    while asyncio.get_running_loop().time() < deadline:
        value = await reader()
        if value is not None and value > before:
            return value
        await asyncio.sleep(1.0)
    return None
