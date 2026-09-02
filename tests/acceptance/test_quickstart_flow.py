"""T125 FS-001 quickstart validation gate.

The quickstart gate exercises the available deterministic implementation and
checks deployment/presentation boundaries without manufacturing live-service
results.  External service checks remain separate, environment-qualified
regressions when their endpoints and credentials are configured.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.events.authority import payload_checksum
from backend.observability.evaluation import build_evaluation_trace
from evaluation.runner import EvaluationRunner
from evaluation.sealed_store import SealedStore
from packages.contracts.events import EventEnvelope, EventType
from projections.neo4j_projection import Neo4jProjection
from replay.mode_selection import select_mode
from replay.runner import run_live_or_replay, run_replay
from replay.variants import available_variants, run_variant

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FIXTURE = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "canonical" / "incident.json"
)
COMPOSE_FILES = (
    REPOSITORY_ROOT / "infra" / "docker-compose.yml",
    REPOSITORY_ROOT / "infra" / "docker-compose.test.yml",
    REPOSITORY_ROOT / "infra" / "networks.yml",
)
EXPECTED_SERVICES = {
    "web",
    "api",
    "workflow-worker",
    "model-gateway",
    "attribution",
    "evidence-connectors",
    "action-gateway",
    "postgres",
    "temporal",
    "redpanda",
    "neo4j",
    "minio",
    "redis",
    "keycloak",
    "vault",
    "otel-collector",
    "prometheus",
    "grafana",
    "loki",
    "langfuse",
    "mlflow",
}
REQUIRED_VARIANTS = {
    "invalid_signature",
    "duplicate_delivery",
    "duplicate_events",
    "out_of_order_events",
    "missing_evidence",
    "partial_unavailable_evidence",
    "policy_denial",
    "approval_required",
    "approval_rejected",
    "approval_expired",
    "forbidden_proposal",
    "unknown_remote_result",
    "reconciliation_before_retry",
    "verification_failure",
    "inconclusive_verification",
    "escalation",
    "model_unavailability",
    "provider_unavailability",
    "replay_fallback",
    "duplicate_action_attempt",
}
TERMINAL_STATES = {
    "verified_contained",
    "verified_failed",
    "escalated_unresolved",
}


def _fixture() -> dict[str, Any]:
    return json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))


def _canonical_run() -> dict[str, Any]:
    fixture = _fixture()
    return run_replay(
        fixture=fixture,
        fixture_version=fixture["fixture_version"],
        deterministic_seed=fixture["deterministic_seed"],
    )


def test_quickstart_canonical_flow_is_explicit_and_reproducible() -> None:
    fixture = _fixture()
    first = _canonical_run()
    second = _canonical_run()

    assert first == second
    assert first["mode"] == first["label"] == "replay"
    assert first["side_effects"] is False
    assert first["remote_side_effects"] == []
    assert set(first["stage_outcomes"]) == set(fixture["expected_stage_outcomes"])
    assert all(first["stage_outcomes"].values())
    assert first["terminal_state"] in TERMINAL_STATES
    assert first["terminal_state"] == fixture["expected_results"]["terminal_state"]
    assert not first["differences_from_expected"]

    expected_exposure = fixture["expected_results"]
    exposure = first["exposure"]
    for field in (
        "gross_exposure_minor",
        "recoverable_value_minor",
        "contained_value_minor",
        "legitimate_value_disrupted_minor",
        "remaining_exposure_minor",
        "currency",
    ):
        assert exposure[field] == expected_exposure[field]

    labels_by_event: dict[str, set[str]] = {}
    for attribution in first["attribution"]:
        labels_by_event.setdefault(attribution["timeline_event_id"], set()).add(
            attribution["label"]
        )
    for event_id, label in fixture["expected_results"]["attribution_labels"].items():
        assert label in labels_by_event[event_id]
    assert {"malicious", "legitimate", "uncertain"} <= set(
        label for labels in labels_by_event.values() for label in labels
    )

    assert first["policy_decision"]["result"] == "approval_required"
    assert first["approval"]["status"] == "approved"
    assert first["approval"]["separation_of_duties"] is True
    assert first["action"]["simulation"] is True
    assert first["reconciliation"]["retry_before_reconciliation"] is False
    assert first["verification"]["approval_gated_action"] == "inconclusive"
    assert first["escalation"]["owner"]

    audit_stages = {record["stage"] for record in first["audit"]}
    expected_audit_stages = {link["stage"] for link in fixture["audit_links"]}
    assert expected_audit_stages <= audit_stages
    assert all(record["tenant_id"] == fixture["tenant_id"] for record in first["audit"])
    assert all(record["case_id"] == fixture["case_id"] for record in first["audit"])


def test_quickstart_live_request_is_truthfully_replayed_when_unqualified() -> None:
    fixture = _fixture()
    result = run_live_or_replay(
        mode="live",
        fixture=fixture,
        fixture_version=fixture["fixture_version"],
        deterministic_seed=fixture["deterministic_seed"],
    )
    assert result["requested_mode"] == "live"
    assert result["provenance"]["effective_mode"] == "replay"
    assert result["provenance"]["final_mode"] == "replay"
    assert result["mode"] == result["label"] == "replay"
    assert result["fallback_reason"]
    assert result["live_execution_occurred"] is False
    assert result["side_effects"] is False

    selected = select_mode("live")
    assert selected.final_mode == "replay"
    assert selected.effective_mode == "replay"
    assert selected.live_execution_occurred is False
    assert selected.fallback_reason


def test_quickstart_variants_are_explicit_and_side_effect_free() -> None:
    assert REQUIRED_VARIANTS <= set(available_variants())
    results = [
        run_variant(variant=name, deterministic_seed=125, mode="replay")
        for name in sorted(REQUIRED_VARIANTS)
    ]
    assert {result["variant"] for result in results} == REQUIRED_VARIANTS
    assert all(result["mode"] == result["label"] == "replay" for result in results)
    assert all(result["side_effects"] is False for result in results)
    assert all(not result["remote_side_effects"] for result in results)
    assert all(
        isinstance(result["outcome"], str) and result["outcome"] for result in results
    )

    by_variant = {result["variant"]: result for result in results}
    assert by_variant["forbidden_proposal"]["outcome"] == "rejected"
    assert by_variant["unknown_remote_result"]["outcome"] == "reconciled"
    assert by_variant["reconciliation_before_retry"]["outcome"] == "reconciled"
    assert by_variant["duplicate_action_attempt"]["outcome"] == "duplicate"
    assert by_variant["inconclusive_verification"]["outcome"] == (
        "escalated_unresolved"
    )


def test_quickstart_evaluation_metadata_and_held_out_controls_are_honest() -> None:
    manifest = (REPOSITORY_ROOT / "evaluation" / "manifest.yaml").read_text(
        encoding="utf-8"
    )
    for line in (
        "case_count: 0",
        "available_case_count: 0",
        "held_out_sealed: true",
        "generated_case_count: 0",
        "assignments_frozen_before_overlay: true",
    ):
        assert line in manifest

    cases = (
        {
            "actual_label": "malicious",
            "predicted_label": "malicious",
            "action_attempted": True,
            "action_forbidden": False,
            "action_executed": True,
            "contained_value_minor": 10_000,
            "legitimate_value_disrupted_minor": 0,
            "resolved": True,
            "latency_ms": 120,
            "tool_calls": 2,
            "model_cost": 0.03,
            "split": "development",
        },
        {
            "actual_label": "legitimate",
            "predicted_label": "legitimate",
            "action_attempted": False,
            "action_forbidden": False,
            "action_executed": False,
            "contained_value_minor": 0,
            "legitimate_value_disrupted_minor": 0,
            "resolved": True,
            "latency_ms": 80,
            "tool_calls": 1,
            "model_cost": 0.02,
            "split": "development",
        },
        {
            "actual_label": "uncertain",
            "predicted_label": "uncertain",
            "action_attempted": True,
            "action_forbidden": True,
            "action_executed": False,
            "contained_value_minor": 0,
            "legitimate_value_disrupted_minor": 0,
            "resolved": False,
            "latency_ms": 160,
            "tool_calls": 3,
            "model_cost": 0.04,
            "split": "development",
        },
    )
    provenance = {
        "dataset_version": "development-v1.0.0",
        "split": "development",
        "policy_version_id": "policy-v1.0.0",
        "model_version": "replay-fixture/provider-v1.0.0",
        "environment": "deterministic-test",
    }
    report = EvaluationRunner().run(cases, provenance=provenance, seed=125)
    assert report["actual_sample_size"] == 3
    assert report["provenance"] == provenance
    assert report["confidence_intervals"]
    assert report["synthetic_is_not_production"] is True
    assert report["side_effects"] is False

    store = SealedStore()
    reference = store.seal(
        {"scenario": "sealed-value"},
        case_identity="held-out-case",
        seed="held-out-seed",
        scenario="held-out-scenario",
    )
    with pytest.raises(PermissionError):
        store.read(reference, operation="model_selection")
    authorization = store.authorize_final_evaluation(
        evaluation_run_id="evaluation-run-t125",
        reason="explicit final evaluation gate",
    )
    assert store.read(reference, authorization) == {"scenario": "sealed-value"}


def test_quickstart_projection_rebuild_preserves_tenant_scoped_event_set() -> None:
    driver = _ProjectionDriver()
    projection = Neo4jProjection(driver)
    projection.bootstrap()
    early = _event("event-early", datetime(2026, 9, 1, 9, 0, tzinfo=UTC))
    late = _event("event-late", datetime(2026, 9, 1, 9, 1, tzinfo=UTC))

    assert projection.apply(late) == "event-late"
    result = projection.rebuild("tenant-canonical-demo", (late, early))
    assert result.tenant_id == "tenant-canonical-demo"
    assert result.applied_events == 2
    assert result.deleted_nodes == 2
    assert driver.applied_event_ids[-2:] == ["event-early", "event-late"]

    with pytest.raises(ValueError, match="tenant boundary"):
        projection.rebuild(
            "tenant-canonical-demo",
            (early.model_copy(update={"tenant_id": "other-tenant"}),),
        )


def test_quickstart_observability_is_redacted_correlated_and_non_authoritative() -> (
    None
):
    trace = build_evaluation_trace(
        tenant_id="tenant-canonical-demo",
        correlation_id="correlation-canonical-demo-001",
        case_id="case-canonical-demo-001",
        evaluation_run_id="evaluation-run-t125",
        metric_report_id="metrics-t125",
        mode="replay",
        data={
            "provider": "replay-fixture",
            "policy_version_id": "policy-v1.0.0",
            "raw_evidence": "must not appear",
            "prompt": "must not appear",
            "credentials": "must not appear",
            "outcome": "escalated_unresolved",
        },
    )
    assert trace["mode"] == trace["label"] == "replay"
    assert trace["non_authoritative"] is True
    assert trace["side_effects"] is False
    assert trace["trace_correlation"] == {
        "evaluation_run_id": "evaluation-run-t125",
        "case_id": "case-canonical-demo-001",
        "correlation_id": "correlation-canonical-demo-001",
        "metric_report_id": "metrics-t125",
    }
    assert "raw_evidence" not in trace
    assert "prompt" not in trace
    assert "credentials" not in trace
    assert "provider" in trace

    dashboard = json.loads(
        (
            REPOSITORY_ROOT
            / "infra"
            / "observability"
            / "grafana"
            / "dashboards"
            / "fs001.json"
        ).read_text(encoding="utf-8")
    )
    assert dashboard["editable"] is False
    assert len(dashboard["panels"]) >= 3
    assert any(
        "reclaim_evaluation" in target.get("expr", "")
        for panel in dashboard["panels"]
        for target in panel.get("targets", ())
    )

    for relative_path in (
        "infra/langfuse/config.yaml",
        "infra/mlflow/config.yaml",
    ):
        config = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "enabled: false" in config
        assert "non_authoritative: true" in config
        assert "raw_evidence: false" in config or "record_raw_evidence: false" in config
        assert "held_out_payloads: false" in config


def test_quickstart_compose_configuration_preserves_safe_topology() -> None:
    if shutil.which("docker") is None:
        pytest.skip(
            "Docker CLI is unavailable; Compose config is environment-qualified"
        )
    command = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILES[0]),
        "-f",
        str(COMPOSE_FILES[1]),
        "-f",
        str(COMPOSE_FILES[2]),
        "config",
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    config = json.loads(completed.stdout)
    assert EXPECTED_SERVICES <= set(config["services"])
    assert {
        name
        for name, network in config["networks"].items()
        if network.get("internal") is True
    } >= {"app-services", "data-services", "action-boundary", "observability"}

    exposed = {
        service: tuple(
            (port["host_ip"], port["target"]) for port in definition.get("ports", ())
        )
        for service, definition in config["services"].items()
        if definition.get("ports")
    }
    assert exposed == {"web": (("127.0.0.1", 3000),), "api": (("127.0.0.1", 8000),)}
    assert "ports" not in config["services"]["action-gateway"]

    gateway_environment = config["services"]["action-gateway"]["environment"]
    assert gateway_environment["RECLAIM_LIVE_ACTIONS_ENABLED"] == "false"
    assert gateway_environment["RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED"] == "false"
    model_environment = config["services"]["model-gateway"]["environment"]
    assert (
        model_environment["RECLAIM_MODE_CREDENTIAL_SCOPE"] == "model-gateway-read-only"
    )
    assert not any("ACTION" in key and "CREDENTIAL" in key for key in model_environment)


def test_quickstart_operator_surface_exposes_review_and_mode_truth() -> None:
    ui_files = (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "cases"
        / "[caseId]"
        / "page.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "CaseTimeline.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ExposureSummary.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ActionDecisionPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ApprovalPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "EscalationPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "replay"
        / "ReplayPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "replay"
        / "ModeBadge.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "audit"
        / "AuditTrace.tsx",
        REPOSITORY_ROOT / "frontend" / "src" / "lib" / "api.ts",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in ui_files).lower()
    for term in (
        "tenant",
        "timeline",
        "legitimate",
        "malicious",
        "remaining exposure",
        "approval",
        "escalation",
        "terminal",
        "audit",
        "replay",
        "live",
    ):
        assert term in source
    assert "aria-label" in source
    assert "read-only" in source
    assert "no remote side effects" in source
    assert "delete" not in source
    assert "insert" not in source
    assert "update" not in source


def _event(
    event_id: str, occurred_at: datetime, tenant_id: str = "tenant-canonical-demo"
) -> EventEnvelope:
    payload = {"stage": event_id}
    return EventEnvelope(
        tenant_id=tenant_id,
        correlation_id="correlation-canonical-demo-001",
        event_id=event_id,
        event_type=EventType.INCIDENT_ACCEPTED,
        aggregate_type="incident",
        aggregate_id="incident-canonical-demo-001",
        occurred_at=occurred_at,
        produced_at=occurred_at + timedelta(seconds=1),
        causation_id="command-t125",
        producer="t125-acceptance@1.0.0",
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


class _ProjectionResult:
    def __init__(self, event_id: str | None = None, deleted_nodes: int = 2) -> None:
        self.event_id = event_id
        self.deleted_nodes = deleted_nodes

    def single(self) -> dict[str, str] | None:
        return None if self.event_id is None else {"event_id": self.event_id}

    def consume(self) -> SimpleNamespace:
        return SimpleNamespace(
            counters=SimpleNamespace(nodes_deleted=self.deleted_nodes)
        )


class _ProjectionSession:
    def __init__(self, driver: _ProjectionDriver) -> None:
        self.driver = driver

    def __enter__(self) -> _ProjectionSession:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback

    def run(self, query: str, **parameters: object) -> _ProjectionResult:
        if "RETURN event.event_id AS event_id" in query:
            self.driver.applied_event_ids.append(str(parameters["event_id"]))
            return _ProjectionResult(str(parameters["event_id"]), 0)
        return _ProjectionResult(deleted_nodes=2)


class _ProjectionDriver:
    def __init__(self) -> None:
        self.applied_event_ids: list[str] = []

    def session(self, **kwargs: object) -> _ProjectionSession:
        del kwargs
        return _ProjectionSession(self)

    def close(self) -> None:
        return None
