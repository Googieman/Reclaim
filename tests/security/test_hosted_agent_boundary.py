"""Security checks for the separately authenticated agent service."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from agent.litellm_gateway import LiteLLMProviderAdapter
from agent.server import create_agent_service_app
from model_gateway.server import ModelGatewayClient, ModelGatewayRequest, create_model_gateway_app
from packages.contracts.analysis_policy import ModelAnalysisRequest, ModelBudget, ProviderMode


def _request() -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id="tenant-hosted-agent",
        correlation_id="correlation-hosted-agent",
        case_id="case-hosted-agent",
        redacted_case_representation={"timeline": [], "evidence": [], "uncertainty": []},
        policy_version_id="policy-hosted-agent",
        budget=ModelBudget(max_tokens=128, max_tool_calls=0, timeout_seconds=5),
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )


def _completion(**_: Any) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "analysis_id": "analysis-hosted-agent",
                            "provider": "trusted-provider",
                            "model": "trusted-model",
                            "tenant_id": "tenant-hosted-agent",
                            "case_id": "case-hosted-agent",
                            "correlation_id": "correlation-hosted-agent",
                            "attributions": [],
                            "proposals": [],
                            "uncertainty": "bounded",
                            "refusal_records": [],
                        }
                    )
                }
            }
        ],
        "usage": {"total_tokens": 7},
    }


def test_agent_service_requires_authenticated_service_and_typed_request() -> None:
    provider = LiteLLMProviderAdapter(
        provider="trusted-provider",
        model="trusted-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    model_app = create_model_gateway_app(
        providers={"reclaim-specialist": provider},
        service_authorizer=lambda value: value == "agent-service",
    )
    model_http = TestClient(model_app)

    def send(payload: ModelGatewayRequest) -> dict[str, Any]:
        result = model_http.post(
            "/v1/model/complete",
            json=payload.model_dump(mode="json"),
            headers={"Authorization": "Bearer agent-service"},
        )
        result.raise_for_status()
        return result.json()

    transport = ModelGatewayClient(
        send,
        profile="reclaim-specialist",
        metadata=provider.metadata,
    )
    app = create_agent_service_app(
        provider=transport,
        service_authorizer=lambda value: value == "api-service",
    )
    client = TestClient(app)
    body = {"profile": "reclaim-specialist", "request": _request().model_dump(mode="json")}

    assert client.post("/v1/agent/analyze", json=body).status_code == 401
    assert client.post(
        "/v1/agent/analyze",
        json=body,
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 403
    response = client.post(
        "/v1/agent/analyze",
        json=body,
        headers={"Authorization": "Bearer api-service"},
    )
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "fresh_agent"
    assert response.json()["remote_side_effects"] == []


def test_agent_service_rejects_request_transport_override() -> None:
    provider = LiteLLMProviderAdapter(
        provider="trusted-provider",
        model="trusted-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    app = create_agent_service_app(
        provider=provider,
        service_authorizer=lambda value: value == "api-service",
    )
    response = TestClient(app).post(
        "/v1/agent/analyze",
        json={
            "profile": "reclaim-specialist",
            "request": _request().model_dump(mode="json"),
            "model": "caller-selected-model",
            "api_base": "https://attacker.invalid/v1",
        },
        headers={"Authorization": "Bearer api-service"},
    )
    assert response.status_code == 422
