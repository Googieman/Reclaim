"""T104 contract coverage for replay runs and evaluation records."""

from datetime import UTC, datetime

import pytest

from packages.contracts.audit_replay import EvaluationCase, ReplayRun


WHEN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _replay_run(**overrides: object) -> ReplayRun:
    values: dict[str, object] = {
        "tenant_id": "tenant-t104",
        "correlation_id": "correlation-t104",
        "run_id": "run-t104",
        "fixture_version": "canonical-v1.0.0",
        "connector_simulator_version": "evidence-simulator-v1.0.0",
        "action_simulator_version": "action-simulator-v1.0.0",
        "policy_version_id": "policy-v1.0.0",
        "model_provider_mode": "replay-fixture/provider-v1.0.0",
        "deterministic_seed": 104,
        "environment_metadata": {
            "runtime": "python-3.12",
            "executor": "pytest",
            "provider_available": False,
        },
        "mode": "replay",
        "stage_outcomes": {
            "intake": "accepted",
            "timeline": "rebuilt",
            "policy": "approval_required",
            "terminal": "escalated_unresolved",
        },
        "terminal_state": "escalated_unresolved",
        "differences_from_expected": (),
    }
    values.update(overrides)
    return ReplayRun(**values)


def test_replay_run_retains_versioned_provenance_and_outcomes() -> None:
    run = _replay_run()

    assert run.fixture_version == "canonical-v1.0.0"
    assert run.connector_simulator_version == "evidence-simulator-v1.0.0"
    assert run.action_simulator_version == "action-simulator-v1.0.0"
    assert run.policy_version_id == "policy-v1.0.0"
    assert run.model_provider_mode == "replay-fixture/provider-v1.0.0"
    assert run.environment_metadata["provider_available"] is False
    assert run.deterministic_seed == 104
    assert run.stage_outcomes["terminal"] == "escalated_unresolved"
    assert run.terminal_state == "escalated_unresolved"
    assert run.differences_from_expected == ()
    assert run.mode.value == "replay"
    assert run.label == "replay"


def test_evaluation_case_retains_split_grouping_labels_and_metric_metadata() -> None:
    case = EvaluationCase(
        tenant_id="tenant-t104",
        correlation_id="correlation-t104",
        evaluation_case_id="evaluation-case-t104",
        provenance={
            "fixture_version": "canonical-v1.0.0",
            "dataset_version": "development-v1.0.0",
            "seed": "development-seed-t104",
            "environment": "deterministic-test",
        },
        label_source="reviewed_fixture",
        split="held_out",
        entity_group_id="merchant-group-t104",
        customer_group_id="customer-group-t104",
        temporal_boundary=WHEN,
        synthetic_overlay_lineage="overlay-after-leakage-split-v1.0.0",
        class_labels=("malicious", "legitimate", "uncertain"),
        no_compromise_false_alert=False,
        mixed_legitimate_malicious=True,
        expected_outcomes={
            "attribution": ("malicious", "legitimate", "uncertain"),
            "terminal_state": "verified_contained",
        },
        observed_outcomes={
            "attribution": ("malicious", "legitimate", "uncertain"),
            "terminal_state": "verified_contained",
        },
        leakage_checks={"entity": True, "customer": True, "temporal": True},
        held_out_access_policy="sealed-and-inaccessible-to-tuning",
        confidence_interval_metadata={
            "method": "wilson",
            "confidence_level": 0.95,
            "sample_size": 1,
        },
        metric_references=("metrics-report-t104",),
    )

    assert case.split.value == "held_out"
    assert case.entity_group_id == "merchant-group-t104"
    assert case.customer_group_id == "customer-group-t104"
    assert case.temporal_boundary == WHEN
    assert case.class_labels == ("malicious", "legitimate", "uncertain")
    assert case.no_compromise_false_alert is False
    assert case.mixed_legitimate_malicious is True
    assert case.expected_outcomes == case.observed_outcomes
    assert all(case.leakage_checks.values())
    assert case.held_out_access_policy == "sealed-and-inaccessible-to-tuning"
    assert case.confidence_interval_metadata["confidence_level"] == 0.95
    assert case.metric_references == ("metrics-report-t104",)


def test_replay_run_cannot_claim_live_label() -> None:
    with pytest.raises(ValueError, match="replay label"):
        _replay_run(label="live")
