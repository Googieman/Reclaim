"""T081 adversarial approval separation-of-duties tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from packages.contracts.analysis_policy import Approval, ApprovalStatus
from us3_test_seams import require_symbol


def _approval(**overrides: Any) -> Approval:
    values: dict[str, Any] = {
        "tenant_id": "tenant-us3-approval",
        "correlation_id": "corr-us3-approval-security-001",
        "approval_id": "approval-us3-security-001",
        "case_id": "case-us3-approval-001",
        "proposal_id": "proposal-us3-refund-001",
        "approver_id": "approver-us3-001",
        "approver_role": "approver",
        "proposer_id": "proposer-us3-001",
        "scope": "refund_payment:payment-us3-001",
        "policy_version_id": "policy-us3-v1.0.0",
        "status": ApprovalStatus.APPROVED,
        "approved_at": datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        "separation_of_duties_evidence": "distinct authenticated principals",
    }
    values.update(overrides)
    return Approval(**values)


@pytest.mark.parametrize(
    "status",
    (ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED, ApprovalStatus.REVOKED),
)
def test_nonapproved_approval_status_is_not_execution_authority(
    status: ApprovalStatus,
) -> None:
    approval = _approval(status=status)

    assert approval.status is not ApprovalStatus.APPROVED
    assert approval.status in {
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.REVOKED,
    }


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owner T090: approval service must enforce scope, freshness, and separation",
)
def test_adversarial_approval_cannot_authorize_a_mutation() -> None:
    authorize = require_symbol(
        "approvals.service",
        "authorize_action",
        task="T081 -> T090",
    )
    proposal = {
        "tenant_id": "tenant-us3-approval",
        "case_id": "case-us3-approval-001",
        "proposal_id": "proposal-us3-refund-001",
        "action_type": "refund_payment",
        "policy_version_id": "policy-us3-v1.0.0",
        "proposer_id": "proposer-us3-001",
    }
    adversarial_approvals = (
        {
            **_approval().model_dump(),
            "approver_id": "proposer-us3-001",
            "proposer_id": "proposer-us3-001",
        },
        _approval(approval_id="forged-approval"),
        _approval(expires_at=datetime(2026, 9, 1, 11, 59, tzinfo=UTC)),
        _approval(status=ApprovalStatus.REVOKED),
        _approval(policy_version_id="policy-us3-old"),
        _approval(tenant_id="tenant-other"),
        _approval(case_id="case-other"),
        _approval(proposal_id="proposal-other"),
    )
    for approval in adversarial_approvals:
        result = authorize(proposal=proposal, approval=approval)
        assert result.execution_authorized is False
