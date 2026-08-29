from datetime import datetime, timezone

import pytest

from packages.contracts.analysis_policy import (
    ActionType,
    Approval,
    ApprovalStatus,
    ModelAnalysisRequest,
    ModelBudget,
    PolicyDecision,
    PolicyResult,
    TypedActionProposal,
)


def test_model_request_is_bounded_and_tenant_scoped() -> None:
    request = ModelAnalysisRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        redacted_case_representation={"timeline": []},
        allowed_tools=("read_case",),
        policy_version_id="policy-1",
        budget=ModelBudget(max_tokens=500, max_tool_calls=2),
        provider_mode="replay",
        replay_label="replay",
    )
    assert request.budget.max_tool_calls == 2
    with pytest.raises(ValueError, match="forbidden model tools"):
        ModelAnalysisRequest(
            tenant_id="tenant-a",
            correlation_id="corr-1",
            case_id="case-1",
            redacted_case_representation={"timeline": []},
            allowed_tools=("refund",),
            policy_version_id="policy-1",
            budget=ModelBudget(max_tokens=500),
            provider_mode="replay",
            replay_label="replay",
        )


def test_proposal_currency_and_policy_approval_rules_are_explicit() -> None:
    with pytest.raises(ValueError, match="explicit currency"):
        TypedActionProposal(
            tenant_id="tenant-a",
            correlation_id="corr-1",
            proposal_id="p-1",
            case_id="case-1",
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-1",
            rationale="captured payment",
            requested_amount_minor=100,
            idempotency_key="p-1-key",
            analysis_id="analysis-1",
        )
    decision = PolicyDecision(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        decision_id="d-1",
        case_id="case-1",
        proposal_id="p-1",
        policy_version_id="policy-1",
        result=PolicyResult.APPROVAL_REQUIRED,
        evaluated_conditions={"amount": "within_bound"},
        evaluator_version="policy-evaluator-1",
        decided_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert decision.result == "approval_required"
    with pytest.raises(ValueError, match="distinct"):
        Approval(
            tenant_id="tenant-a",
            correlation_id="corr-1",
            approval_id="a-1",
            case_id="case-1",
            proposal_id="p-1",
            approver_id="same-user",
            proposer_id="same-user",
            approver_role="approver",
            scope="refund",
            policy_version_id="policy-1",
            status=ApprovalStatus.APPROVED,
            approved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            separation_of_duties_evidence="role separation",
        )
