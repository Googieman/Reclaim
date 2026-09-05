"""Deterministic deviations from the canonical replay fixture."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .runner import ReplayRunner

VARIANT_VERSION = "replay-variants-v1.0.0"

VARIANT_SPECS: dict[str, dict[str, Any]] = {
    "invalid_signature": {"outcome": "quarantined", "stage": "incident", "field": "signature"},
    "duplicate_delivery": {"outcome": "duplicate", "stage": "incident", "field": "delivery"},
    "duplicate_events": {"outcome": "duplicate", "stage": "timeline", "field": "events"},
    "out_of_order_events": {"outcome": "converged", "stage": "timeline", "field": "ordering"},
    "missing_evidence": {
        "outcome": "escalated_unresolved",
        "stage": "evidence",
        "field": "evidence",
    },
    "partial_unavailable_evidence": {
        "outcome": "escalated_unresolved",
        "stage": "evidence",
        "field": "availability",
    },
    "policy_denial": {"outcome": "denied", "stage": "policy", "field": "result"},
    "approval_gating": {"outcome": "approval_required", "stage": "policy", "field": "approval"},
    "approval_required": {"outcome": "approval_required", "stage": "policy", "field": "approval"},
    "approval_rejected": {"outcome": "rejected", "stage": "approval", "field": "status"},
    "approval_expired": {"outcome": "expired", "stage": "approval", "field": "status"},
    "forbidden_proposal": {"outcome": "rejected", "stage": "proposal", "field": "capability"},
    "unknown_remote_result": {
        "outcome": "reconciled",
        "stage": "reconciliation",
        "field": "remote_result",
    },
    "reconciliation_before_retry": {
        "outcome": "reconciled",
        "stage": "reconciliation",
        "field": "retry_order",
    },
    "verification_failure": {
        "outcome": "verified_failed",
        "stage": "verification",
        "field": "result",
    },
    "inconclusive_verification": {
        "outcome": "escalated_unresolved",
        "stage": "verification",
        "field": "result",
    },
    "escalation": {"outcome": "escalated_unresolved", "stage": "escalation", "field": "state"},
    "provider_unavailability": {"outcome": "replay", "stage": "model", "field": "availability"},
    "model_unavailability": {"outcome": "replay", "stage": "model", "field": "availability"},
    "replay_fallback": {"outcome": "replay", "stage": "model", "field": "mode"},
    "duplicate_action_attempt": {"outcome": "duplicate", "stage": "action", "field": "attempt"},
}

_ALIASES = {
    "provider_unavailable": "provider_unavailability",
    "model_unavailable": "model_unavailability",
}


def run_variant(
    *,
    variant: str,
    fixture_version: str = "canonical-v1.0.0",
    deterministic_seed: str | int = 0,
    mode: str = "replay",
    runner: ReplayRunner | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run one named deviation with no connector or Action Gateway authority."""

    canonical_name = _ALIASES.get(variant, variant)
    try:
        spec = VARIANT_SPECS[canonical_name]
    except KeyError as exc:
        raise ValueError(f"unsupported replay variant: {variant}") from exc
    if str(mode).lower() not in {"replay", "live"}:
        raise ValueError("variant mode must be live or replay")
    base = (runner or ReplayRunner()).run(
        fixture_version=fixture_version,
        deterministic_seed=deterministic_seed,
        mode="replay",
        **kwargs,
    )
    result = copy.deepcopy(base)
    seed = str(deterministic_seed)
    deviation = {
        "canonical_fixture_version": fixture_version,
        "stage": spec["stage"],
        "field": spec["field"],
        "operation": "replace canonical value with declared variant condition",
        "canonical_value_unchanged_elsewhere": False,
    }
    result.update(
        {
            "variant": variant,
            "variant_identity": f"{VARIANT_VERSION}:{canonical_name}",
            "variant_version": VARIANT_VERSION,
            "outcome": spec["outcome"],
            "mode": "replay",
            "label": "replay",
            "remote_side_effects": (),
            "side_effects": False,
            "deviation": deviation,
            "deterministic_seed": seed,
            "provenance": {
                **dict(result.get("provenance", {})),
                "variant_identity": f"{VARIANT_VERSION}:{canonical_name}",
                "variant_version": VARIANT_VERSION,
                "canonical_fixture_version": fixture_version,
                "requested_mode": str(mode).lower(),
                "effective_mode": "replay",
                "final_mode": "replay",
                "label": "replay",
                "side_effects": False,
            },
        }
    )
    stage_outcomes = dict(result.get("stage_outcomes", {}))
    stage_outcomes[spec["stage"]] = spec["outcome"]
    result["stage_outcomes"] = stage_outcomes
    _apply_coherent_variant(result, canonical_name)
    terminal_state = str(result.get("terminal_state", "escalated_unresolved"))
    result["stage_outcomes"]["terminal"] = terminal_state
    replay_run = dict(result.get("replay_run", {}))
    replay_run["stage_outcomes"] = dict(result["stage_outcomes"])
    replay_run["terminal_state"] = terminal_state
    replay_run["differences_from_expected"] = (
        f"{spec['stage']}.{spec['field']} deviated for {canonical_name}",
    )
    result["replay_run"] = replay_run
    result["differences_from_expected"] = (
        f"{spec['stage']}.{spec['field']} deviated for {canonical_name}",
    )
    result["provenance"]["run_checksum"] = _checksum(
        {key: value for key, value in result.items() if key != "provenance"}
    )
    result["result_checksum"] = _checksum(result)
    return result


def available_variants() -> tuple[str, ...]:
    return tuple(sorted(VARIANT_SPECS))


def _apply_coherent_variant(result: dict[str, Any], variant: str) -> None:
    """Update nested replay state so a variant cannot contradict its summary."""

    result.setdefault("incident_result", {"status": "accepted"})
    result.setdefault("evidence_result", {"status": "collected"})
    result.setdefault("model_result", {"status": "available", "mode": "replay"})
    policy = result.setdefault("policy_decision", {})
    approval = result.setdefault("approval", {})
    proposal = result.setdefault("proposal_validation", {})
    action = result.setdefault("action", {})
    reconciliation = result.setdefault("reconciliation", {})
    verification = result.setdefault("verification", {})
    escalation = result.setdefault("escalation", {})

    if variant == "invalid_signature":
        result["incident_result"].update(status="quarantined", signature="invalid")
    elif variant == "duplicate_delivery":
        result["incident_result"].update(status="duplicate", delivery="deduplicated")
    elif variant == "duplicate_events":
        if result.get("timeline"):
            result["timeline"][0]["duplicate_count"] = max(
                2, int(result["timeline"][0].get("duplicate_count", 1))
            )
    elif variant == "out_of_order_events":
        result["timeline_convergence"] = {
            "input_order": "out_of_order",
            "output_order": "canonical",
            "status": "converged",
        }
    elif variant == "missing_evidence":
        result["evidence_result"].update(status="missing", completeness="none")
        escalation.update(state="escalated_unresolved", reason="required evidence is missing")
    elif variant == "partial_unavailable_evidence":
        result["evidence_result"].update(status="partially_unavailable", completeness="partial")
        escalation.update(
            state="escalated_unresolved", reason="required evidence is partially unavailable"
        )
    elif variant == "policy_denial":
        policy["result"] = "deny"
        proposal["status"] = "denied_by_policy"
        approval.update(status="not_required", reason="policy denied the proposal")
        _mark_action_not_executed(action, "policy_denied")
    elif variant in {"approval_gating", "approval_required"}:
        policy["result"] = "approval_required"
        approval.update(status="required", request_id="approval-variant-required")
        _mark_action_not_executed(action, "approval_required")
    elif variant == "approval_rejected":
        approval.update(status="rejected", reason="independent approver rejected the request")
        _mark_action_not_executed(action, "approval_rejected")
    elif variant == "approval_expired":
        approval.update(status="expired", reason="approval window expired")
        _mark_action_not_executed(action, "approval_expired")
    elif variant == "forbidden_proposal":
        proposal.update(status="rejected", capability="forbidden")
        policy["result"] = "deny"
        _mark_action_not_executed(action, "forbidden_proposal")
    elif variant in {"unknown_remote_result", "reconciliation_before_retry"}:
        reconciliation.update(
            status="reconciled_before_retry",
            unknown_result=True,
            retry_before_reconciliation=False,
        )
        action["reconciliation_state"] = "reconciled_before_retry"
    elif variant == "verification_failure":
        verification["approval_gated_action"] = "verified_failure"
        escalation.update(state="open", reason="merchant state proves the action failed")
        result["terminal_state"] = "verified_failed"
    elif variant == "inconclusive_verification":
        verification["approval_gated_action"] = "inconclusive"
        escalation.update(state="escalated_unresolved", reason="verification is inconclusive")
        result["terminal_state"] = "escalated_unresolved"
    elif variant == "escalation":
        escalation.update(state="escalated_unresolved")
        result["terminal_state"] = "escalated_unresolved"
    elif variant in {"provider_unavailability", "model_unavailability"}:
        result["model_result"].update(status="unavailable", mode="replay_fallback")
    elif variant == "replay_fallback":
        result["model_result"].update(status="fallback", mode="replay")
    elif variant == "duplicate_action_attempt":
        action["attempt_result"] = "duplicate_suppressed"
        action["duplicate_remote_request_issued"] = False

    result["remote_side_effects"] = ()
    result["side_effects"] = False
    if isinstance(action, dict):
        action["remote_side_effects"] = ()
        action["simulation"] = True


def _mark_action_not_executed(action: dict[str, Any], reason: str) -> None:
    action["status"] = "simulated_not_executed"
    action["blocked_reason"] = reason
    gated = action.get("approval_gated")
    if isinstance(gated, dict):
        gated["execution"] = "simulated_not_executed"


def _checksum(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


__all__ = ["VARIANT_SPECS", "VARIANT_VERSION", "available_variants", "run_variant"]
