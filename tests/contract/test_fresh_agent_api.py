"""Contract coverage for the separate fresh-agent API surface."""

from __future__ import annotations

import json
from typing import Any

from agent.litellm_gateway import LiteLLMProviderAdapter
from api.main import create_app
from app.config import Settings
from fastapi.testclient import TestClient

from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


def request_factory(
    tenant_id: str, case_id: str, budget: ModelBudget
) -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=tenant_id,
        correlation_id="correlation-api-fresh",
        case_id=case_id,
        redacted_case_representation={
            "timeline": [{"timeline_event_id": "timeline-api"}],
            "evidence": [{"evidence_id": "evidence-api"}],
            "uncertainty": [],
        },
        evidence_references=("evidence-api",),
        allowed_tools=(),
        policy_version_id="policy-api-fresh",
        budget=budget,
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )


def response(**_: Any) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "analysis_id": "analysis-api-fresh",
                            "provider": "api-test-provider",
                            "model": "api-test-model",
                            "tenant_id": "tenant-api",
                            "case_id": "case-api",
                            "correlation_id": "correlation-api-fresh",
                            "attributions": [],
                            "proposals": [],
                            "uncertainty": "No model uncertainty beyond bounded review.",
                            "refusal_records": [],
                        }
                    )
                }
            }
        ],
        "usage": {"total_tokens": 21},
    }


def test_fresh_agent_route_is_separate_from_replay_and_tenant_scoped() -> None:
    provider = LiteLLMProviderAdapter(
        provider="api-test-provider",
        model="api-test-model",
        mode=ProviderMode.LIVE,
        completion=response,
    )
    app = create_app(
        settings=Settings(fresh_agent_enabled=True, demo_read_only_enabled=False),
        agent_provider=provider,
        agent_request_factory=request_factory,
    )
    client = TestClient(app)

    started = client.post(
        "/tenants/tenant-api/cases/case-api/agent-runs",
        json={"provider_profile": "reclaim-specialist"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["execution_mode"] == "fresh_agent"
    assert body["provider_mode"] == "live"
    assert body["remote_side_effects"] == []
    assert (
        client.get(
            f"/tenants/tenant-api/cases/case-api/agent-runs/{body['run_id']}"
        ).json()["run_id"]
        == body["run_id"]
    )


def test_fresh_agent_route_exposes_a_typed_persistence_boundary() -> None:
    provider = LiteLLMProviderAdapter(
        provider="api-test-provider",
        model="api-test-model",
        mode=ProviderMode.LIVE,
        completion=response,
    )
    persisted: list[Any] = []
    app = create_app(
        settings=Settings(fresh_agent_enabled=True),
        agent_provider=provider,
        agent_request_factory=request_factory,
        agent_run_persistence=persisted.append,
    )

    result = TestClient(app).post(
        "/tenants/tenant-api/cases/case-api/agent-runs", json={}
    )

    assert result.status_code == 200
    assert len(persisted) == 1
    assert persisted[0].execution_mode == "fresh_agent"
    assert persisted[0].request_checksum
    assert persisted[0].response_checksum
    assert persisted[0].to_dict()["remote_side_effects"] == []


def test_fresh_agent_route_rejects_arbitrary_request_fields() -> None:
    app = create_app(
        settings=Settings(fresh_agent_enabled=True),
        agent_provider=object(),
        agent_request_factory=request_factory,
    )
    response = TestClient(app).post(
        "/tenants/tenant-api/cases/case-api/agent-runs",
        json={"shell": "Get-ChildItem"},
    )
    assert response.status_code == 422
