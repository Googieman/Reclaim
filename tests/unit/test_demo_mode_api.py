"""T124 read-only mode API and tenant authorization coverage."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.demo import create_demo_router
from replay.mode_selection import select_mode


class StubOIDCVerifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def authorize(self, token: str, **kwargs: object) -> dict[str, object]:
        self.calls.append({"token": token, **kwargs})
        return {"subject": "reviewer"}


def test_tenant_mode_exposes_server_decision_not_client_qualification() -> None:
    app = FastAPI()
    app.include_router(
        create_demo_router(
            availability_provider=lambda: select_mode(
                "replay", provider_available=True
            ),
        ),
    )

    response = TestClient(app).get(
        "/tenants/merchant-a/demo/mode?requested_mode=live",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "merchant-a"
    assert payload["requested_mode"] == "replay"
    assert payload["final_mode"] == "replay"
    assert payload["live_execution_occurred"] is False


def test_tenant_mode_requires_reviewer_authorization_when_wired() -> None:
    verifier = StubOIDCVerifier()
    app = FastAPI()
    app.include_router(create_demo_router(oidc_verifier=verifier))
    client = TestClient(app)

    missing = client.get("/tenants/merchant-a/demo/mode")
    authorized = client.get(
        "/tenants/merchant-a/demo/mode",
        headers={"Authorization": "Bearer reviewer-token"},
    )

    assert missing.status_code == 401
    assert authorized.status_code == 200
    assert verifier.calls[0]["tenant_id"] == "merchant-a"
