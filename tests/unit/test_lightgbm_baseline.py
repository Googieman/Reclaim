"""Test-first parity coverage for the advisory LightGBM baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion
from us2_test_seams import require_symbol


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "tests"
    / "fixtures"
    / "attribution"
    / "lightgbm"
    / "baseline-v1.0.0.json"
)


def load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def test_baseline_fixture_records_replay_provenance_without_performance_claim() -> None:
    fixture = load_fixture()

    assert fixture["schema_version"] == "1.0.0"
    assert fixture["mode"] == "replay"
    assert fixture["provenance"]["model_family"] == "lightgbm"
    assert fixture["provenance"]["model_version"] == fixture["fixture_version"]
    assert fixture["claim_boundary"] == {
        "production_performance_claim": False,
        "metrics": None,
    }
    assert set(fixture["feature_schema"]) == {
        "payment_amount_minor",
        "new_device",
        "profile_change_24h",
        "session_velocity_5m",
        "successful_customer_orders",
    }


def test_baseline_fixture_links_each_prediction_to_authoritative_inputs() -> None:
    fixture = load_fixture()

    for event in fixture["events"]:
        assert event["timeline_event_id"] in event["input_references"]
        assert set(event["evidence_references"]).issubset(event["input_references"])
        assert event["expected"]["method"] == "lightgbm"
        assert event["expected"]["model_or_rules_version"] == fixture["fixture_version"]
        assert event["expected"]["label"] in {
            AttributionLabel.MALICIOUS.value,
            AttributionLabel.LEGITIMATE.value,
            AttributionLabel.UNCERTAIN.value,
        }


def _adapter(fixture: dict[str, Any]) -> Any:
    adapter_type = require_symbol(
        "attribution.lightgbm_adapter",
        "LightGBMBaselineAdapter",
        task="T060/T067",
    )
    from_fixture = getattr(adapter_type, "from_fixture", None)
    if from_fixture is None:
        raise AssertionError(
            "T060/T067 production seam is missing: "
            "LightGBMBaselineAdapter.from_fixture"
        )
    return from_fixture(fixture)


def _predict(adapter: Any, fixture: dict[str, Any], event: dict[str, Any]) -> Any:
    predict = getattr(adapter, "predict", None)
    if predict is None:
        raise AssertionError("T060/T067 production seam is missing: adapter.predict")
    return predict(
        tenant_id=fixture["tenant_id"],
        case_id=fixture["case_id"],
        timeline_event_id=event["timeline_event_id"],
        feature_vector=event["feature_vector"],
        evidence_references=tuple(event["evidence_references"]),
    )


def test_lightgbm_adapter_matches_fixture_outputs_and_retains_provenance() -> None:
    fixture = load_fixture()
    adapter = _adapter(fixture)

    for event in fixture["events"]:
        result = _predict(adapter, fixture, event)
        assert isinstance(result, AttributionSuggestion)
        expected = event["expected"]
        assert result.timeline_event_id == event["timeline_event_id"]
        assert result.evidence_references == tuple(event["evidence_references"])
        assert result.label is AttributionLabel(expected["label"])
        assert result.confidence == expected["confidence"]
        assert result.rationale == expected["rationale"]
        assert result.method == expected["method"]
        assert result.model_or_rules_version == expected["model_or_rules_version"]


def test_lightgbm_adapter_is_order_independent_and_replay_deterministic() -> None:
    fixture = load_fixture()
    adapter = _adapter(fixture)
    events = fixture["events"]

    forward = tuple(
        _predict(adapter, fixture, event).model_dump(mode="json") for event in events
    )
    reverse = tuple(
        _predict(adapter, fixture, event).model_dump(mode="json")
        for event in reversed(events)
    )

    assert forward == tuple(reversed(reverse))
    assert forward == tuple(
        _predict(adapter, fixture, event).model_dump(mode="json") for event in events
    )


def test_lightgbm_adapter_rejects_unsupported_features_and_missing_evidence() -> None:
    fixture = load_fixture()
    adapter = _adapter(fixture)
    event = fixture["events"][0]

    with pytest.raises(ValueError):
        adapter.predict(
            tenant_id=fixture["tenant_id"],
            case_id=fixture["case_id"],
            timeline_event_id=event["timeline_event_id"],
            feature_vector={**event["feature_vector"], "unsupported_fact": 1},
            evidence_references=tuple(event["evidence_references"]),
        )
    with pytest.raises(ValueError):
        adapter.predict(
            tenant_id=fixture["tenant_id"],
            case_id=fixture["case_id"],
            timeline_event_id=event["timeline_event_id"],
            feature_vector=event["feature_vector"],
            evidence_references=(),
        )


def test_lightgbm_adapter_rejects_stale_model_provenance() -> None:
    fixture = load_fixture()
    stale_fixture = {
        **fixture,
        "provenance": {
            **fixture["provenance"],
            "model_version": "lightgbm-baseline-v0.9.0",
        },
    }
    adapter_type = require_symbol(
        "attribution.lightgbm_adapter",
        "LightGBMBaselineAdapter",
        task="T060/T067",
    )
    from_fixture = getattr(adapter_type, "from_fixture", None)
    if from_fixture is None:
        raise AssertionError(
            "T060/T067 production seam is missing: "
            "LightGBMBaselineAdapter.from_fixture"
        )

    with pytest.raises(ValueError):
        from_fixture(stale_fixture)
