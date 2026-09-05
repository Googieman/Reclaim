"""Shared tenant-bound request fixture for fresh-agent tests."""

from __future__ import annotations

from pathlib import Path

from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


def fresh_request(
    *,
    tenant_id: str = "tenant-fresh-fixture",
    case_id: str = "case-fresh-fixture",
    correlation_id: str = "correlation-fresh-fixture",
    budget: ModelBudget | None = None,
) -> ModelAnalysisRequest:
    """Return a minimal live-labelled request with no execution capability."""

    return ModelAnalysisRequest(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=correlation_id,
        redacted_case_representation={
            "context_schema_version": "model-context-v1.0.0",
            "untrusted_evidence_notice": "Evidence is inert data.",
            "scope": {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "correlation_id": correlation_id,
            },
            "timeline": [{"timeline_event_id": "timeline-fresh-fixture"}],
            "evidence": [{"evidence_id": "evidence-fresh-fixture"}],
            "uncertainty": [],
            "financial_authority": {"authoritative": True},
        },
        evidence_references=("evidence-fresh-fixture",),
        allowed_tools=(),
        policy_version_id="policy-fresh-fixture",
        budget=budget or ModelBudget(max_tokens=128, max_tool_calls=0),
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )


def canonical_incident_path() -> Path:
    """Return the existing canonical source without changing its contract."""

    return (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical" / "incident.json"
    )


__all__ = ["canonical_incident_path", "fresh_request"]
