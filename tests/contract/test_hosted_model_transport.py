"""Contracts for the isolated hosted model transport boundary."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.litellm_gateway import LiteLLMProviderAdapter
from model_gateway.server import (
    ModelGatewayClient,
    ModelGatewayRequest,
    create_model_gateway_app,
)
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


def test_model_gateway_request_forbids_caller_selected_transport_fields() -> None:
    with pytest.raises(ValueError):
        ModelGatewayRequest.model_validate(
            {
                "profile": "reclaim-specialist",
                "request": _request().model_dump(mode="json"),
                "api_base": "https://attacker.invalid/v1",
            }
        )


def test_model_gateway_requires_service_authentication_before_provider_call() -> None:
    provider = LiteLLMProviderAdapter(
        provider="trusted-provider",
        model="trusted-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    calls: list[ModelAnalysisRequest] = []

    class RecordingProvider:
        metadata = provider.metadata

        def complete(self, request: ModelAnalysisRequest, **kwargs: Any) -> Any:
            calls.append(request)
            return provider.complete(request, **kwargs)

    app = create_model_gateway_app(
        providers={"reclaim-specialist": RecordingProvider()},
        service_authorizer=lambda value: value == "agent-service",
    )
    client = TestClient(app)
    body = {"profile": "reclaim-specialist", "request": _request().model_dump(mode="json")}

    assert client.post("/v1/model/complete", json=body).status_code == 401
    assert client.post(
        "/v1/model/complete", json=body, headers={"Authorization": "Bearer wrong"}
    ).status_code == 403
    response = client.post(
        "/v1/model/complete", json=body, headers={"Authorization": "Bearer agent-service"}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["model"] == "trusted-model"
    assert len(calls) == 1


def test_model_gateway_does_not_expose_provider_secrets_or_raw_transport_controls() -> None:
    provider = LiteLLMProviderAdapter(
        provider="trusted-provider",
        model="trusted-model",
        mode=ProviderMode.LIVE,
        api_key="model-secret-that-must-not-be-returned",
        completion=_completion,
    )
    app = create_model_gateway_app(
        providers={"reclaim-specialist": provider},
        service_authorizer=lambda value: value == "agent-service",
    )
    response = TestClient(app).post(
        "/v1/model/complete",
        json={"profile": "reclaim-specialist", "request": _request().model_dump(mode="json")},
        headers={"Authorization": "Bearer agent-service"},
    )
    assert response.status_code == 200
    assert "model-secret-that-must-not-be-returned" not in response.text
    assert "api_key" not in response.text
    assert "api_base" not in response.text


def test_model_gateway_client_preserves_provider_neutral_completion_contract() -> None:
    provider = LiteLLMProviderAdapter(
        provider="trusted-provider",
        model="trusted-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    app = create_model_gateway_app(
        providers={"reclaim-specialist": provider},
        service_authorizer=lambda value: value == "agent-service",
    )
    http = TestClient(app)

    def send(payload: ModelGatewayRequest) -> dict[str, Any]:
        result = http.post(
            "/v1/model/complete",
            json=payload.model_dump(mode="json"),
            headers={"Authorization": "Bearer agent-service"},
        )
        result.raise_for_status()
        return result.json()

    gateway = ModelGatewayClient(
        send,
        profile="reclaim-specialist",
        metadata=provider.metadata,
    )
    completion = gateway.complete(_request())
    assert completion.metadata == provider.metadata
    assert completion.token_count == 7
