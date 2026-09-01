"""Security expectations for rejected proposals and zero remote effects."""

from __future__ import annotations

from typing import Any

import pytest

from us2_test_seams import require_symbol


class RemoteEffectProbe:
    """A test spy that must remain untouched when validation rejects a proposal."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit(self, request: dict[str, Any]) -> None:
        self.calls.append(request)


def forbidden_output(operation: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "tenant_id": "tenant-us2-forbidden",
        "correlation_id": f"corr-forbidden-{operation}",
        "analysis_id": "analysis-us2-forbidden",
        "proposal_id": f"proposal-forbidden-{operation}",
        "case_id": "case-us2-forbidden",
        "action_type": "hold_fulfillment",
        "target_resource": "fulfillment-1",
        "parameters": {"operation": operation},
        "rationale": "Untrusted analysis output.",
        "evidence_references": ["evidence-forbidden-1"],
        "attribution_references": ["timeline-forbidden-1"],
        "idempotency_key": f"forbidden-{operation}",
    }


@pytest.mark.xfail(
    strict=True,
    reason="T064 rejection/audit coverage is expected red until T074/T075 exist",
)
@pytest.mark.parametrize(
    "operation",
    (
        "execute_payment",
        "execute_refund",
        "cancel_order_without_approval",
        "restore_identity_without_approval",
        "database_write",
        "shell_command",
        "arbitrary_network",
        "attacker_interaction",
        "credential_probe",
    ),
)
def test_forbidden_proposal_is_rejected_audited_and_never_submitted(
    operation: str,
) -> None:
    boundary_type = require_symbol(
        "agent.proposals",
        "TypedProposalBoundary",
        task="T064/T074",
    )
    boundary = boundary_type()
    remote_effects = RemoteEffectProbe()
    process = getattr(boundary, "process", None)
    if process is None:
        raise AssertionError(
            "T064/T074 production seam is missing: TypedProposalBoundary.process"
        )

    result = process(
        raw_output=forbidden_output(operation),
        remote_action_gateway=remote_effects,
    )

    status = (
        result.get("status") if isinstance(result, dict) else getattr(result, "status")
    )
    audit = (
        result.get("audit_record")
        if isinstance(result, dict)
        else getattr(result, "audit_record")
    )
    outcome = (
        audit.get("outcome") if isinstance(audit, dict) else getattr(audit, "outcome")
    )

    assert status in {"rejected", "quarantined"}
    assert audit is not None
    assert outcome in {"rejected", "forbidden_operation"}
    assert remote_effects.calls == []
