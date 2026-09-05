from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from api.main import create_app
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.config import Settings
from fastapi.testclient import TestClient


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
) -> Any:
    original_client = httpx.Client

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    try:
        return create_app(
            settings=_settings(
                help_chat_enabled=True,
                help_gateway_base="https://gateway.internal",
                help_gateway_token=token,
            ),
            oidc_verifier=FakeVerifier(),
        )
    finally:
        monkeypatch.setattr(httpx, "Client", original_client)


def test_enabled_help_without_verified_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="verified identity"):
        create_app(
            settings=_settings(
                help_chat_enabled=True,
                help_gateway_base="https://gateway.internal",
                help_gateway_token="gateway-secret",
            )
        )


def test_enabled_help_without_gateway_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="private model gateway"):
        create_app(settings=_settings(help_chat_enabled=True), oidc_verifier=FakeVerifier())


def test_gateway_failure_is_safe_and_does_not_leak_secret_or_raw_body(monkeypatch: Any) -> None:
    secret = "gateway-secret"
    raw_body = f"upstream failure {secret}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=raw_body, request=request)

    application = _app_with_mock_gateway(monkeypatch, handler, token=secret)
    with TestClient(application) as client:
        response = client.post(
            "/help/chat",
            headers={"Authorization": "Bearer reviewer-token", "X-Tenant-ID": "tenant-a"},
            json={"question": "How do I verify a webhook?"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert secret not in response.text
    assert raw_body not in response.text


def test_oversized_gateway_body_becomes_safe_unavailable_result(monkeypatch: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 70_000, request=request)

    application = _app_with_mock_gateway(monkeypatch, handler)
    with TestClient(application) as client:
        response = client.post(
            "/help/chat",
            headers={"Authorization": "Bearer reviewer-token", "X-Tenant-ID": "tenant-a"},
            json={"question": "How do I verify a webhook?"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
