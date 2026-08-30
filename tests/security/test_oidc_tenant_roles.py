"""Keycloak/OIDC signature, tenant, and role boundary tests."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.auth.oidc import OIDCVerifier, RequiredRole, TenantAuthorizationError


def token(*, tenant_ids: list[str], roles: list[str]) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://identity.example/realms/reclaim",
            "aud": "reclaim-api",
            "sub": "reviewer-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_ids": tenant_ids,
            "realm_access": {"roles": roles},
        },
        "test-only-signing-key",
        algorithm="HS256",
    )


def test_oidc_verifies_signature_tenant_and_role() -> None:
    verifier = OIDCVerifier(
        issuer="https://identity.example/realms/reclaim",
        audience="reclaim-api",
        signing_key="test-only-signing-key",
        algorithms=("HS256",),
    )

    principal = verifier.verify(
        token(tenant_ids=["tenant-a"], roles=["reviewer", "approver"]),
        tenant_id="tenant-a",
        required_role=RequiredRole.APPROVER,
    )

    assert principal.subject == "reviewer-1"
    assert principal.can_access_tenant("tenant-a")


def test_oidc_rejects_cross_tenant_and_invalid_signature() -> None:
    verifier = OIDCVerifier(
        issuer="https://identity.example/realms/reclaim",
        audience="reclaim-api",
        signing_key="test-only-signing-key",
        algorithms=("HS256",),
    )
    with pytest.raises(TenantAuthorizationError, match="tenant"):
        verifier.verify(
            token(tenant_ids=["tenant-a"], roles=["reviewer"]), tenant_id="tenant-b"
        )
    with pytest.raises(TenantAuthorizationError, match="verification failed"):
        OIDCVerifier(
            issuer="https://identity.example/realms/reclaim",
            audience="reclaim-api",
            signing_key="wrong-key",
            algorithms=("HS256",),
        ).verify(
            token(tenant_ids=["tenant-a"], roles=["reviewer"]), tenant_id="tenant-a"
        )
