"""Strict Keycloak/OIDC JWT verification with tenant-aware roles."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import jwt


class TenantAuthorizationError(PermissionError):
    """Raised for invalid identity, tenant scope, or role use."""


class RequiredRole(StrEnum):
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ESCALATION_OWNER = "escalation-owner"
    POLICY_OWNER = "policy-owner"


class IdentityType(StrEnum):
    USER = "user"
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    tenant_ids: frozenset[str]
    roles: frozenset[str]
    identity_type: IdentityType
    issuer: str

    def can_access_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self.tenant_ids

    def require_tenant(self, tenant_id: str) -> None:
        if not self.can_access_tenant(tenant_id):
            raise TenantAuthorizationError("identity is not scoped to the requested tenant")

    def require_role(self, role: RequiredRole | str, *, tenant_id: str) -> None:
        self.require_tenant(tenant_id)
        if str(role) not in self.roles:
            raise TenantAuthorizationError(f"identity lacks required role: {role}")


class OIDCVerifier:
    """Verify signed OIDC tokens; no unverified decode path is exposed."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        signing_key: str | bytes | None = None,
        jwks_url: str | None = None,
        algorithms: Iterable[str] = ("RS256",),
    ) -> None:
        if not issuer.strip() or not audience.strip():
            raise ValueError("OIDC issuer and audience are required")
        self.issuer = issuer
        self.audience = audience
        self.signing_key = signing_key
        self.jwks_url = jwks_url
        self.algorithms = tuple(algorithms)
        allowed_algorithms = {"RS256", "RS384", "RS512", "HS256"}
        if not self.algorithms or any(
            algorithm not in allowed_algorithms for algorithm in self.algorithms
        ):
            raise ValueError("OIDC verifier algorithms are not allowlisted")
        if signing_key is None and not jwks_url:
            raise ValueError("a signing key or JWKS URL is required")

    def verify(
        self, token: str, *, tenant_id: str, required_role: RequiredRole | str | None = None
    ) -> AuthenticatedPrincipal:
        if not token.strip():
            raise TenantAuthorizationError("OIDC token is required")
        key = self.signing_key
        if key is None:
            if self.jwks_url is None:
                raise TenantAuthorizationError("OIDC verification key is unavailable")
            from jwt import PyJWKClient

            key = PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token).key
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise TenantAuthorizationError("OIDC token verification failed") from exc
        principal = self.principal_from_claims(claims)
        principal.require_tenant(tenant_id)
        if required_role is not None:
            principal.require_role(required_role, tenant_id=tenant_id)
        return principal

    def principal_from_claims(self, claims: dict[str, Any]) -> AuthenticatedPrincipal:
        subject = _required_text(claims, "sub")
        issuer = _required_text(claims, "iss")
        if issuer != self.issuer:
            raise TenantAuthorizationError("OIDC issuer claim does not match configuration")
        raw_tenants = claims.get("tenant_ids", claims.get("tenant_id"))
        tenant_ids = _string_set(raw_tenants)
        if not tenant_ids:
            raise TenantAuthorizationError("OIDC identity has no tenant scope")
        roles = set(_string_set(claims.get("roles")))
        realm_access = claims.get("realm_access")
        if isinstance(realm_access, dict):
            roles.update(_string_set(realm_access.get("roles")))
        resource_access = claims.get("resource_access")
        if isinstance(resource_access, dict):
            for client_roles in resource_access.values():
                if isinstance(client_roles, dict):
                    roles.update(_string_set(client_roles.get("roles")))
        identity_type = (
            IdentityType.SERVICE if claims.get("service_identity") else IdentityType.USER
        )
        return AuthenticatedPrincipal(
            subject, frozenset(tenant_ids), frozenset(roles), identity_type, issuer
        )


def _required_text(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TenantAuthorizationError(f"OIDC claim {name} is required")
    return value


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value.strip() else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {item for item in value if isinstance(item, str) and item.strip()}
    return set()
