from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import pytest

from model_gateway.main import build_app_from_environment, create_model_gateway_app
from packages.contracts.help_chat import HelpGatewayResponse


def _provider(_: Any) -> HelpGatewayResponse:
    return HelpGatewayResponse(
        final_text="Use the reviewed documentation.",
        source_ids=("help.boundary",),
        model_revision="deepseek-test",
    )


def test_runtime_is_help_only_and_requires_service_authentication() -> None:
    client = TestClient(
        create_model_gateway_app(help_provider=_provider, service_token="gateway-secret")
    )
    body = {
        "question": "What is the help boundary?",
        "passages": ("[help.boundary] Help assistant boundary",),
    }

    assert client.post("/v1/help/complete", json=body).status_code == 401
    assert client.post(
        "/v1/help/complete",
        headers={"Authorization": "Bearer wrong"},
        json=body,
    ).status_code == 403
    response = client.post(
        "/v1/help/complete",
        headers={"Authorization": "Bearer gateway-secret"},
        json=body,
    )

    assert response.status_code == 200
    assert response.json() == {
        "final_text": "Use the reviewed documentation.",
        "source_ids": ["help.boundary"],
        "model_revision": "deepseek-test",
        "token_count": None,
    }
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.post("/v1/model/complete", json={}).status_code == 404


def test_runtime_rejects_caller_selected_profile_and_transport_fields() -> None:
    client = TestClient(
        create_model_gateway_app(help_provider=_provider, service_token="gateway-secret")
    )
    response = client.post(
        "/v1/help/complete",
        headers={"Authorization": "Bearer gateway-secret"},
        json={
            "profile": "attacker-profile",
            "provider_url": "https://attacker.invalid/v1",
            "transport": "arbitrary",
            "question": "How?",
            "passages": ("[help.boundary] Help assistant boundary",),
        },
    )

    assert response.status_code == 422


def test_environment_factory_requires_gateway_token_and_model_key() -> None:
    with pytest.raises(ValueError, match="RECLAIM_HELP_GATEWAY_TOKEN"):
        build_app_from_environment(
            {
                "MODEL_API_KEY": "model-secret",
                "RECLAIM_HELP_API_BASE": "http://model-help.test/v1",
            }
        )

    app = build_app_from_environment(
        {
            "MODEL_API_KEY": "model-secret",
            "RECLAIM_HELP_API_BASE": "http://model-help.test/v1",
            "RECLAIM_HELP_GATEWAY_TOKEN": "gateway-secret",
        }
    )
    assert TestClient(app).get("/docs").status_code == 404
