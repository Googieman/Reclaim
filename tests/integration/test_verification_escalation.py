"""T085 verification and escalation tests."""

from __future__ import annotations

from datetime import UTC, datetime
import pytest

from packages.contracts.action_gateway import VerificationResponse, VerificationResult
from us3_test_seams import require_symbol


def _verification(result: VerificationResult) -> VerificationResponse:
    return VerificationResponse(
        tenant_id="tenant-us3-verification",
        correlation_id="corr-us3-verification-001",
        verification_id=f"verification-{result.value}",
        execution_id="execution-us3-001",
        observed_resource_state=(
            "revoked" if result is VerificationResult.VERIFIED_SUCCESS else "unknown"
        ),
        verifier_source="merchant-session-store",
        result=result,
        evidence_references=("evidence-session-us3-001", "evidence-audit-us3-001"),
        verified_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize("result", tuple(VerificationResult))
def test_verification_result_contract_distinguishes_success_failure_and_inconclusive(
    result: VerificationResult,
) -> None:
    verification = _verification(result)

    assert verification.result is result
    assert verification.execution_id == "execution-us3-001"
    assert verification.evidence_references == (
        "evidence-session-us3-001",
        "evidence-audit-us3-001",
    )
    if result is VerificationResult.INCONCLUSIVE:
        assert result is not VerificationResult.VERIFIED_SUCCESS


def test_verification_contract_requires_tenant_execution_and_evidence_provenance() -> (
    None
):
    verification = _verification(VerificationResult.VERIFIED_FAILURE)

    assert verification.tenant_id == "tenant-us3-verification"
    assert verification.correlation_id == "corr-us3-verification-001"
    assert verification.execution_id == "execution-us3-001"
    assert verification.verifier_source == "merchant-session-store"
    assert verification.evidence_references


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owners T096/T097: inconclusive verification must escalate with evidence",
)
def test_inconclusive_verification_routes_to_tenant_escalation() -> None:
    route = require_symbol(
        "action_gateway.verification",
        "verify_and_route",
        task="T085 -> T096/T097",
    )
    result = route(
        verification=_verification(VerificationResult.INCONCLUSIVE),
        escalation_owner="tenant-us3-escalation-owner",
        remaining_exposure_minor=30_000,
        currency="INR",
        evidence_references=("evidence-session-us3-001",),
        recommended_human_decision="reconcile merchant state and decide containment",
    )

    assert result.terminal_state == "escalated_unresolved"
    assert result.escalation.owner_id == "tenant-us3-escalation-owner"
    assert result.escalation.remaining_exposure_minor == 30_000
    assert result.escalation.evidence_references
    assert result.escalation.recommended_human_decision
