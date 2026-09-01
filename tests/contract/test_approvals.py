"""T081 approval contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from packages.contracts.analysis_policy import Approval, ApprovalStatus


APPROVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _approval(
    status: ApprovalStatus = ApprovalStatus.APPROVED, **overrides: Any
) -> Approval:
    values: dict[str, Any] = {
        "tenant_id": "tenant-us3-approval",
        "correlation_id": "corr-us3-approval-001",
        "approval_id": "approval-us3-001",
        "case_id": "case-us3-approval-001",
        "proposal_id": "proposal-us3-refund-001",
        "approver_id": "approver-us3-001",
        "approver_role": "approver",
        "proposer_id": "model-runner-us3-001",
        "scope": "refund_payment:payment-us3-001",
        "policy_version_id": "policy-us3-v1.0.0",
        "status": status,
        "approved_at": APPROVED_AT,
        "expires_at": APPROVED_AT + timedelta(hours=1),
        "separation_of_duties_evidence": "distinct authenticated principals",
    }
    values.update(overrides)
    return Approval(**values)


@pytest.mark.parametrize("status", tuple(ApprovalStatus))
def test_approval_contract_retains_lifecycle_and_binding(
    status: ApprovalStatus,
) -> None:
    approval = _approval(status)

    assert approval.status is status
    assert approval.tenant_id == "tenant-us3-approval"
    assert approval.case_id == "case-us3-approval-001"
    assert approval.proposal_id == "proposal-us3-refund-001"
    assert approval.policy_version_id == "policy-us3-v1.0.0"
    assert approval.approver_id != approval.proposer_id
    assert approval.approver_role == "approver"
    assert approval.scope == "refund_payment:payment-us3-001"
    assert approval.separation_of_duties_evidence


def test_approval_contract_supports_expiry_and_revocation_without_granting_them_success() -> (
    None
):
    expired = _approval(ApprovalStatus.EXPIRED)
    revoked = _approval(ApprovalStatus.REVOKED)

    assert expired.status == ApprovalStatus.EXPIRED
    assert revoked.status == ApprovalStatus.REVOKED
    assert expired.status is not ApprovalStatus.APPROVED
    assert revoked.status is not ApprovalStatus.APPROVED


def test_approval_rejects_self_approval_and_non_forward_expiry() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        _approval(approver_id="same-principal", proposer_id="same-principal")

    with pytest.raises(ValidationError, match="expiry"):
        _approval(expires_at=APPROVED_AT)

    with pytest.raises(ValidationError, match="expiry"):
        _approval(expires_at=APPROVED_AT - timedelta(seconds=1))


def test_approval_rejects_missing_binding_context_and_unknown_fields() -> None:
    values = _approval().model_dump()
    values.pop("policy_version_id")
    with pytest.raises(ValidationError):
        Approval.model_validate(values)

    values = _approval().model_dump()
    values["execute_refund"] = True
    with pytest.raises(ValidationError):
        Approval.model_validate(values)


def test_approval_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _approval(approved_at=datetime(2026, 9, 1, 12, 0))


def test_approval_contract_has_exactly_the_repository_status_values() -> None:
    assert tuple(status.value for status in ApprovalStatus) == (
        "approved",
        "rejected",
        "expired",
        "revoked",
    )
