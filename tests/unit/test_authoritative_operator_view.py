"""Focused tests for the PostgreSQL-backed operator case projection."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.local_runtime import _agent_analysis_payload


def test_agent_analysis_projection_retains_typed_result_and_authority() -> None:
    audit = SimpleNamespace(
        analysis_id="analysis-1",
        tenant_id="tenant-1",
        case_id="case-1",
        correlation_id="corr-1",
        mode="live",
        terminal_outcome="completed",
        provider="local",
        model="specialist",
        uncertainty=("review required",),
        refusal_records=(),
        request_checksum="request-checksum",
        response_checksum="response-checksum",
        deterministic_analysis_checksum="analysis-checksum",
        deterministic_exposure_checksum="exposure-checksum",
        created_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
        provenance={
            "agent_run_id": "agent-run-1",
            "authoritative_store": "postgresql",
            "typed_response": {
                "attributions": [
                    {
                        "timeline_event_id": "event-1",
                        "label": "uncertain",
                        "confidence": 0.71,
                        "rationale": "Needs review",
                        "evidence_references": ["evidence-1"],
                    }
                ],
                "refusal_records": [],
            },
        },
    )

    payload = _agent_analysis_payload(audit)

    assert payload["analysis_id"] == "analysis-1"
    assert payload["run_id"] == "agent-run-1"
    assert payload["status"] == "completed"
    assert payload["attributions"][0]["label"] == "uncertain"
    assert payload["uncertainty"] == ["review required"]
    assert payload["provenance"] == {
        "authoritative_store": "postgresql",
        "request_checksum": "request-checksum",
        "response_checksum": "response-checksum",
        "deterministic_analysis_checksum": "analysis-checksum",
        "deterministic_exposure_checksum": "exposure-checksum",
    }
