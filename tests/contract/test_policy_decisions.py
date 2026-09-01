"""T079 contract coverage for deterministic policy decisions.

The evaluator is intentionally not implemented here.  These tests constrain
the shared decision value and the data that a future evaluator must retain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from packages.contracts.analysis_policy import PolicyDecision, PolicyResult
from packages.contracts.schema_registry import SchemaDefinition, SchemaRegistry


DECIDED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _evaluated_conditions() -> dict[str, Any]:
    return {
        "permission": {
            "action": "revoke_suspicious_session",
            "operation": "revoke_suspicious_session",
            "allowed": True,
        },
        "confidence": {"value": 0.97, "threshold": 0.90},
        "authoritative_resource_state": {
            "resource_id": "session-us3-001",
            "resource_state": "active",
            "connector_id": "session-actions",
        },
        "amount": {"minor": 0, "currency": "INR"},
        "reversibility": {"is_reversible": True},
        "customer_impact": {"class": "bounded", "legitimate_value_at_risk_minor": 0},
        "approval": {"required": False, "state": "not_required"},
        "policy_version": "policy-us3-v1.0.0",
        "schema_version": "1.0.0",
        "provenance": {
            "correlation_id": "corr-us3-policy-001",
            "causation_id": "proposal-us3-001",
            "input_references": ["timeline-us3-001", "resource-us3-001"],
        },
    }


def _decision(**overrides: Any) -> PolicyDecision:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "tenant_id": "tenant-us3-policy",
        "correlation_id": "corr-us3-policy-001",
        "decision_id": "decision-us3-001",
        "case_id": "case-us3-policy-001",
        "proposal_id": "proposal-us3-001",
        "policy_version_id": "policy-us3-v1.0.0",
        "result": PolicyResult.ALLOW,
        "evaluated_conditions": _evaluated_conditions(),
        "evaluator_version": "deterministic-policy-evaluator-v1.0.0",
        "decided_at": DECIDED_AT,
    }
    values.update(overrides)
    return PolicyDecision(**values)


@pytest.mark.parametrize("result", tuple(PolicyResult))
def test_policy_decision_has_exactly_one_closed_set_result(
    result: PolicyResult,
) -> None:
    decision = _decision(result=result)

    assert decision.result is result
    assert isinstance(decision.result, PolicyResult)
    assert tuple(item.value for item in PolicyResult) == (
        "allow",
        "deny",
        "approval_required",
        "escalate",
    )


def test_policy_decision_retains_authority_conditions_and_provenance() -> None:
    decision = _decision()

    assert decision.tenant_id == "tenant-us3-policy"
    assert decision.case_id == "case-us3-policy-001"
    assert decision.proposal_id == "proposal-us3-001"
    assert decision.policy_version_id == "policy-us3-v1.0.0"
    assert decision.evaluated_conditions == _evaluated_conditions()
    assert decision.evaluated_conditions["permission"]["action"] == (
        "revoke_suspicious_session"
    )
    assert decision.evaluated_conditions["confidence"]["value"] == 0.97
    assert decision.evaluated_conditions["authoritative_resource_state"][
        "resource_state"
    ] == ("active")
    assert decision.evaluated_conditions["amount"] == {"minor": 0, "currency": "INR"}
    assert decision.evaluated_conditions["reversibility"]["is_reversible"] is True
    assert decision.evaluated_conditions["customer_impact"]["class"] == "bounded"
    assert decision.evaluated_conditions["approval"] == {
        "required": False,
        "state": "not_required",
    }
    assert decision.evaluator_version == "deterministic-policy-evaluator-v1.0.0"
    assert decision.schema_version == "1.0.0"
    assert decision.correlation_id == "corr-us3-policy-001"
    assert decision.decided_at == DECIDED_AT


@pytest.mark.parametrize(
    "missing_field",
    (
        "tenant_id",
        "correlation_id",
        "decision_id",
        "case_id",
        "proposal_id",
        "policy_version_id",
        "result",
        "evaluated_conditions",
        "evaluator_version",
        "decided_at",
    ),
)
def test_policy_decision_rejects_missing_required_fields(missing_field: str) -> None:
    values = _decision().model_dump()
    values.pop(missing_field)

    with pytest.raises(ValidationError):
        PolicyDecision.model_validate(values)


@pytest.mark.parametrize(
    "malformed_result", ("unknown", "allow|deny", ("allow", "deny"))
)
def test_policy_decision_rejects_unknown_or_multiple_results(
    malformed_result: object,
) -> None:
    with pytest.raises(ValidationError):
        _decision(result=malformed_result)


def test_policy_decision_rejects_extra_fields_and_naive_timestamp() -> None:
    values = _decision().model_dump()
    values["unexpected_authority"] = "model"
    with pytest.raises(ValidationError):
        PolicyDecision.model_validate(values)

    with pytest.raises(ValidationError, match="timezone"):
        _decision(decided_at=datetime(2026, 9, 1, 12, 0))


def test_policy_decision_schema_compatibility_is_rejected_by_shared_registry() -> None:
    registry = SchemaRegistry(
        [
            SchemaDefinition(
                name="policy-decision", model=PolicyDecision, version="1.0.0"
            )
        ]
    )

    assert registry.is_compatible("1.0.0") is True
    assert registry.is_compatible("2.0.0") is False
    with pytest.raises(ValueError, match="incompatible"):
        registry.register(
            SchemaDefinition(
                name="future-policy-decision", model=PolicyDecision, version="2.0.0"
            )
        )
