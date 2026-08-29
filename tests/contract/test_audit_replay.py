from datetime import datetime, timezone

import pytest

from packages.contracts.audit_replay import AuditRecord, EvaluationCase, ReplayRun


def test_audit_record_is_checksum_linked_and_replay_is_labeled() -> None:
    record = AuditRecord(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        audit_id="audit-1",
        case_id="case-1",
        actor="intake-api",
        action="incident.accepted",
        input_references=("report-1",),
        outcome="accepted",
        recorded_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        record_checksum="sha256:record",
    )
    run = ReplayRun(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        run_id="run-1",
        fixture_version="fixture-1",
        connector_simulator_version="connectors-1",
        action_simulator_version="actions-1",
        policy_version_id="policy-1",
        model_provider_mode="replay",
        deterministic_seed=7,
        environment_metadata={"runtime": "node22/python312"},
        mode="replay",
        stage_outcomes={"intake": "accepted"},
    )
    assert record.record_checksum.startswith("sha256:")
    assert run.label == "replay"
    with pytest.raises(ValueError, match="replay label"):
        ReplayRun(
            **run.model_dump(exclude={"label"}),
            label="live",
        )


def test_evaluation_case_requires_grouping_temporal_and_holdout_access_metadata() -> None:
    case = EvaluationCase(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        evaluation_case_id="eval-1",
        provenance={"source": "fixture"},
        label_source="fixture-label",
        split="held_out",
        entity_group_id="merchant-1",
        temporal_boundary=datetime(2026, 8, 30, tzinfo=timezone.utc),
        class_labels=("no_compromise",),
        no_compromise_false_alert=True,
        mixed_legitimate_malicious=False,
        expected_outcomes={"terminal_state": "escalated_unresolved"},
        leakage_checks={"entity": True, "temporal": True},
        held_out_access_policy="sealed",
    )
    assert case.split == "held_out"
