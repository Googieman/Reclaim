from __future__ import annotations

from fastapi.testclient import TestClient

from agent.providers import ReplayProvider
from model_gateway.server import create_model_gateway_app
from packages.contracts.help_chat import HelpGatewayResponse


def test_help_gateway_operation_is_authenticated_and_profile_bound() -> None:
    app = create_model_gateway_app(
        providers={"investigator": ReplayProvider(response={})},
        service_authorizer=lambda token: token == "agent-service",
        help_provider=lambda request: HelpGatewayResponse(
            final_text="Use the reviewed documentation.",
            source_ids=("help.boundary",),
            model_revision="deepseek-test",
        ),
    )
    client = TestClient(app)

    body = {
        "question": "What is the help boundary?",
        "passages": ("[help.boundary] Help assistant boundary",),
    }
    assert client.post("/v1/help/complete", json=body).status_code == 401
    response = client.post(
        "/v1/help/complete",
        headers={"Authorization": "Bearer agent-service"},
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["source_ids"] == ["help.boundary"]


def test_help_gateway_rejects_caller_selected_profile() -> None:
    app = create_model_gateway_app(
        providers={"investigator": ReplayProvider(response={})},
        service_authorizer=lambda token: True,
        help_provider=lambda request: HelpGatewayResponse(
            final_text="answer", source_ids=("help.boundary",), model_revision="test"
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/help/complete",
        headers={"Authorization": "Bearer service"},
        json={
            "profile": "reclaim-specialist",
            "question": "How?",
            "passages": ("[help.boundary] text",),
        },
    )

    assert response.status_code == 422
