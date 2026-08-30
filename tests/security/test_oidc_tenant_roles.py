"""Keycloak/OIDC signature, tenant, and role boundary tests."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.auth.oidc import OIDCVerifier, RequiredRole, TenantAuthorizationError


def token(
    *,
    tenant_ids: list[str],
    roles: list[str],
    tenant_roles: dict[str, list[str]] | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://identity.example/realms/reclaim",
            "aud": "reclaim-api",
            "sub": "reviewer-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_ids": tenant_ids,
            "tenant_roles": tenant_roles,
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
        token(
            tenant_ids=["tenant-a"],
            roles=["reviewer", "approver"],
            tenant_roles={"tenant-a": ["reviewer", "approver"]},
        ),
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
            token(
                tenant_ids=["tenant-a"],
                roles=["reviewer"],
                tenant_roles={"tenant-a": ["reviewer"]},
            ),
            tenant_id="tenant-b",
        )
    with pytest.raises(TenantAuthorizationError, match="verification failed"):
        OIDCVerifier(
            issuer="https://identity.example/realms/reclaim",
            audience="reclaim-api",
            signing_key="wrong-key",
            algorithms=("HS256",),
        ).verify(
            token(
                tenant_ids=["tenant-a"],
                roles=["reviewer"],
                tenant_roles={"tenant-a": ["reviewer"]},
            ),
            tenant_id="tenant-a",
        )


def verifier() -> OIDCVerifier:
    return OIDCVerifier(
        issuer="https://identity.example/realms/reclaim",
        audience="reclaim-api",
        signing_key="test-only-signing-key",
        algorithms=("HS256",),
    )


def test_tenant_a_analyst_cannot_access_tenant_b_data() -> None:
    principal = verifier().verify(
        token(
            tenant_ids=["tenant-a", "tenant-b"],
            roles=["analyst"],
            tenant_roles={"tenant-a": ["analyst"], "tenant-b": ["reviewer"]},
        ),
        tenant_id="tenant-a",
    )

    with pytest.raises(TenantAuthorizationError, match="tenant-b"):
        principal.require_role("analyst", tenant_id="tenant-b")


def test_tenant_a_approver_cannot_approve_tenant_b_actions() -> None:
    principal = verifier().verify(
        token(
            tenant_ids=["tenant-a", "tenant-b"],
            roles=["approver"],
            tenant_roles={"tenant-a": ["approver"], "tenant-b": ["reviewer"]},
        ),
        tenant_id="tenant-a",
    )

    with pytest.raises(TenantAuthorizationError, match="tenant-b"):
        principal.require_role("approver", tenant_id="tenant-b")


def test_global_role_without_tenant_membership_grants_no_tenant_authority() -> None:
    with pytest.raises(TenantAuthorizationError, match="tenant-role binding"):
        verifier().verify(
            token(tenant_ids=["tenant-a"], roles=["approver"], tenant_roles=None),
            tenant_id="tenant-a",
        )


def test_unbound_global_role_is_ignored_for_a_tenant_with_another_role() -> None:
    principal = verifier().verify(
        token(
            tenant_ids=["tenant-a"],
            roles=["approver"],
            tenant_roles={"tenant-a": ["reviewer"]},
        ),
        tenant_id="tenant-a",
    )

    with pytest.raises(TenantAuthorizationError, match="tenant-a"):
        principal.require_role("approver", tenant_id="tenant-a")


def test_caller_supplied_tenant_cannot_override_authenticated_context() -> None:
    with pytest.raises(TenantAuthorizationError, match="tenant"):
        verifier().verify(
            token(
                tenant_ids=["tenant-a"],
                roles=["approver"],
                tenant_roles={"tenant-a": ["approver"]},
            ),
            tenant_id="tenant-b",
            required_role="approver",
        )


def test_missing_tenant_role_binding_is_denied_even_for_global_role() -> None:
    with pytest.raises(TenantAuthorizationError, match="tenant-role binding"):
        verifier().verify(
            token(
                tenant_ids=["tenant-a", "tenant-b"],
                roles=["approver"],
                tenant_roles={"tenant-a": ["approver"]},
            ),
            tenant_id="tenant-a",
        )


def test_valid_same_tenant_authorization_succeeds() -> None:
    verifier().verify(
        token(
            tenant_ids=["tenant-a"],
            roles=["approver"],
            tenant_roles={"tenant-a": ["approver"]},
        ),
        tenant_id="tenant-a",
        required_role="approver",
    )

    context = verifier().authorize(
        token(
            tenant_ids=["tenant-a"],
            roles=["approver"],
            tenant_roles={"tenant-a": ["approver"]},
        ),
        tenant_id="tenant-a",
        required_role="approver",
    )
    assert context.tenant_id == "tenant-a"
    assert context.subject == "reviewer-1"
    assert context.roles == frozenset({"approver"})
