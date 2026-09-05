from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from api.main import create_app
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.config import Settings
from fastapi.testclient import TestClient
from packages.contracts.help_chat import HelpGatewayRequest, HelpGatewayResponse


@dataclass
class FakeVerifier:
    def authorize(
        self,
        token: str,
        *,
        tenant_id: str,
        required_role: str,
    ) -> TenantAuthorizationContext:
        if token != "reviewer-token" or tenant_id != "tenant-a" or str(required_role) != "reviewer":
            raise PermissionError("not authorized")
        return TenantAuthorizationContext(
            subject="reviewer-a",
            tenant_id=tenant_id,
            roles=frozenset({"reviewer"}),
            identity_type=IdentityType.USER,
            issuer="test",
        )


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def _app_with_mock_gateway(
    monkeypatch: Any,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token: str = "gateway-secret",
) -> tuple[Any, dict[str, Any]]:
    original_client = httpx.Client
    client_options: dict[str, Any] = {}

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        client_options.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    try:
        application = create_app(
            settings=_settings(
                help_chat_enabled=True,
                help_gateway_base="https://gateway.internal",
                help_gateway_token=token,
            ),
            oidc_verifier=FakeVerifier(),
        )
    finally:
        monkeypatch.setattr(httpx, "Client", original_client)
    return application, client_options


def test_enabled_help_posts_only_typed_payload_to_private_gateway(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "final_text": "Use the verified webhook contract.",
                "source_ids": ["intake.webhook-verification"],
                "model_revision": "gateway-test",
            },
            request=request,
        )

    application, client_options = _app_with_mock_gateway(monkeypatch, handler)

    with TestClient(application) as client:
        response = client.post(
            "/help/chat",
            headers={"Authorization": "Bearer reviewer-token", "X-Tenant-ID": "tenant-a"},
            json={"question": "How do I verify a webhook?"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://gateway.internal/v1/help/complete"
    assert seen["authorization"] == "Bearer gateway-secret"
    typed_payload = HelpGatewayRequest.model_validate(seen["json"])
    assert typed_payload.question == "How do I verify a webhook?"
    assert typed_payload.profile == "reclaim-help-deepseek"
    assert typed_payload.passages
    assert set(seen["json"]) == set(HelpGatewayRequest.model_fields)
    assert typed_payload.model_dump(mode="json") == seen["json"]
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert client_options["timeout"].connect <= 10
    assert client_options["timeout"].read <= 10


def test_help_remains_disabled_without_explicit_enablement(monkeypatch: Any) -> None:
    def unexpected_client(*args: Any, **kwargs: Any) -> httpx.Client:
        raise AssertionError("the gateway client must not be built when help is disabled")

    monkeypatch.setattr(httpx, "Client", unexpected_client)
    application = create_app(
        settings=_settings(
            help_chat_enabled=False,
            help_gateway_base="not-an-http-url",
            help_gateway_token="",
        ),
        oidc_verifier=FakeVerifier(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/help/chat",
            headers={"Authorization": "Bearer reviewer-token", "X-Tenant-ID": "tenant-a"},
            json={"question": "How?"},
        )

    assert response.status_code == 404


def test_injected_fake_gateway_remains_compatible() -> None:
    class FakeGateway:
        def complete(self, request: HelpGatewayRequest) -> HelpGatewayResponse:
            return HelpGatewayResponse(
                final_text="Use the reviewed documentation.",
                source_ids=("intake.webhook-verification",),
                model_revision="fake-gateway",
            )

    application = create_app(
        settings=_settings(help_chat_enabled=True),
        oidc_verifier=FakeVerifier(),
        help_chat_gateway=FakeGateway(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/help/chat",
            headers={"Authorization": "Bearer reviewer-token", "X-Tenant-ID": "tenant-a"},
            json={"question": "How do I verify a webhook?"},
        )

    assert response.status_code == 200
    assert response.json()["model_revision"] == "fake-gateway"
