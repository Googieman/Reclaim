"""HTTP boundary coverage for tenant-bound authenticated intake."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from api.intake import create_intake_app
from app.auth.oidc import OIDCVerifier
from backend.tests.integration.test_intake_service import MemoryState, make_service

pytest.importorskip("fastapi")


ISSUER = "https://identity.example/realms/reclaim"
AUDIENCE = "reclaim-api"
SIGNING_KEY = "test-only-signing-key"


def token(tenant_id: str = "tenant-a") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "reviewer-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_ids": [tenant_id],
            "tenant_roles": {tenant_id: ["reviewer"]},
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


def payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-api-1",
        "source": "operator",
        "received_at": "2026-08-30T10:00:00Z",
        "reporter_context": {"channel": "console"},
        "report_content": "Account compromise reported.",
        "idempotency_key": "api-intake-1",
    }


def verifier() -> OIDCVerifier:
    return OIDCVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        signing_key=SIGNING_KEY,
        algorithms=("HS256",),
    )


def test_api_derives_tenant_authority_from_verified_path_and_token() -> None:
    from fastapi.testclient import TestClient

    state = MemoryState()
    app = create_intake_app(
        intake_service=make_service(state),
        oidc_verifier=verifier(),
    )

    with TestClient(app) as client:
        accepted = client.post(
            "/tenants/tenant-a/incidents",
            json=payload(),
            headers={"Authorization": f"Bearer {token()}"},
        )
        cross_tenant = client.post(
            "/tenants/tenant-b/incidents",
            json=payload(),
            headers={"Authorization": f"Bearer {token()}"},
        )
        unauthenticated = client.post("/tenants/tenant-a/incidents", json=payload())

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert cross_tenant.status_code == 403
    assert unauthenticated.status_code == 401
