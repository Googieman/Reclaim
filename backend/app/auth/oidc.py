"""Strict Keycloak/OIDC JWT verification with tenant-aware roles."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class TenantAuthorizationError(PermissionError):
    """Raised for invalid identity, tenant scope, or role use."""


class RequiredRole(StrEnum):
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ESCALATION_OWNER = "escalation-owner"
    POLICY_OWNER = "policy-owner"
    ORCHESTRATOR = "orchestrator"


class IdentityType(StrEnum):
    USER = "user"
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class TenantAuthorizationContext:
    """An authenticated principal narrowed to one tenant.

    This is the only authorization context accepted by the PostgreSQL UoW.  The
    tenant and role set are produced by :meth:`AuthenticatedPrincipal.for_tenant`
    after OIDC verification; a request's tenant identifier is never sufficient to
    construct this context.
    """

    subject: str
    tenant_id: str
    roles: frozenset[str]
    identity_type: IdentityType
    issuer: str

    def __post_init__(self) -> None:
        if (
            not self.subject.strip()
            or not self.tenant_id.strip()
            or not self.issuer.strip()
            or not self.roles
            or any(not isinstance(role, str) or not role.strip() for role in self.roles)
        ):
            raise TenantAuthorizationError("authorization context is incomplete")

    def require_role(self, role: RequiredRole | str) -> None:
        if str(role) not in self.roles:
            raise TenantAuthorizationError(
                f"identity lacks required role in tenant {self.tenant_id}: {role}"
            )


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    tenant_ids: frozenset[str]
    tenant_roles: Mapping[str, frozenset[str]]
    identity_type: IdentityType
    issuer: str

    def __post_init__(self) -> None:
        if (
            not self.subject.strip()
            or not self.issuer.strip()
            or not self.tenant_ids
            or any(
                not isinstance(tenant_id, str) or not tenant_id.strip()
                for tenant_id in self.tenant_ids
            )
        ):
            raise TenantAuthorizationError("authenticated principal is incomplete")
        if not isinstance(self.tenant_roles, Mapping):
            raise TenantAuthorizationError("authenticated tenant-role bindings are invalid")
        normalized_bindings = {
            tenant_id: frozenset(roles) for tenant_id, roles in self.tenant_roles.items()
        }
        if set(normalized_bindings) != set(self.tenant_ids):
            raise TenantAuthorizationError(
                "every authenticated tenant must have an explicit tenant-role binding"
            )
        if any(
            not roles or any(not isinstance(role, str) or not role.strip() for role in roles)
            for roles in normalized_bindings.values()
        ):
            raise TenantAuthorizationError("tenant-role bindings must declare at least one role")
        object.__setattr__(self, "tenant_roles", MappingProxyType(normalized_bindings))

    def can_access_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self.tenant_ids

    def require_tenant(self, tenant_id: str) -> None:
        if not self.can_access_tenant(tenant_id):
            raise TenantAuthorizationError("identity is not scoped to the requested tenant")

    def roles_for_tenant(self, tenant_id: str) -> frozenset[str]:
        self.require_tenant(tenant_id)
        return self.tenant_roles[tenant_id]

    def require_role(self, role: RequiredRole | str, *, tenant_id: str) -> None:
        self.for_tenant(tenant_id, required_role=role)

    def for_tenant(
        self, tenant_id: str, *, required_role: RequiredRole | str | None = None
    ) -> TenantAuthorizationContext:
        """Return a single-tenant context after validating membership and role."""

        self.require_tenant(tenant_id)
        context = TenantAuthorizationContext(
            subject=self.subject,
            tenant_id=tenant_id,
            roles=self.roles_for_tenant(tenant_id),
            identity_type=self.identity_type,
            issuer=self.issuer,
        )
        if required_role is not None:
            context.require_role(required_role)
        return context


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
        if jwks_url and not jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS URL must use HTTPS")
        if jwks_url and any(algorithm.startswith("HS") for algorithm in self.algorithms):
            raise ValueError("OIDC JWKS verification cannot use symmetric algorithms")

    def verify(
        self, token: str, *, tenant_id: str, required_role: RequiredRole | str | None = None
    ) -> AuthenticatedPrincipal:
        try:
            import jwt
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging/import smoke path
            raise TenantAuthorizationError("OIDC JWT support is unavailable") from exc
        if not token.strip():
            raise TenantAuthorizationError("OIDC token is required")
        key = self.signing_key
        if key is None:
            if self.jwks_url is None:
                raise TenantAuthorizationError("OIDC verification key is unavailable")
            from jwt import PyJWKClient

            try:
                key = PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token).key
            except Exception as exc:
                # Key discovery is an authentication dependency.  Do not leak
                # transport, DNS, or provider details through the auth boundary.
                raise TenantAuthorizationError("OIDC verification key is unavailable") from exc
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
        if required_role is not None:
            principal.for_tenant(tenant_id, required_role=required_role)
        else:
            principal.require_tenant(tenant_id)
        return principal

    def authorize(
        self, token: str, *, tenant_id: str, required_role: RequiredRole | str | None = None
    ) -> TenantAuthorizationContext:
        """Verify a token and return the authenticated single-tenant context."""

        principal = self.verify(token, tenant_id=tenant_id, required_role=required_role)
        return principal.for_tenant(tenant_id, required_role=required_role)

    def principal_from_claims(self, claims: dict[str, Any]) -> AuthenticatedPrincipal:
        subject = _required_text(claims, "sub")
        issuer = _required_text(claims, "iss")
        if issuer != self.issuer:
            raise TenantAuthorizationError("OIDC issuer claim does not match configuration")
        raw_tenants = claims.get("tenant_ids", claims.get("tenant_id"))
        tenant_ids = _required_string_set(raw_tenants, claim_name="tenant_ids")
        tenant_roles = _tenant_role_bindings(claims.get("tenant_roles"))
        identity_type = (
            IdentityType.SERVICE if claims.get("service_identity") else IdentityType.USER
        )
        return AuthenticatedPrincipal(
            subject, frozenset(tenant_ids), tenant_roles, identity_type, issuer
        )


def _required_text(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TenantAuthorizationError(f"OIDC claim {name} is required")
    return value


def _required_string_set(value: Any, *, claim_name: str) -> set[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set | frozenset):
        values = list(value)
    else:
        raise TenantAuthorizationError(f"OIDC claim {claim_name} is invalid")
    if not values or any(not isinstance(item, str) or not item.strip() for item in values):
        raise TenantAuthorizationError(f"OIDC claim {claim_name} is invalid")
    return set(values)


def _tenant_role_bindings(value: Any) -> dict[str, frozenset[str]]:
    """Parse the signed composite ``tenant_roles`` claim without flattening it."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TenantAuthorizationError("OIDC tenant-role binding is invalid") from exc
    if not isinstance(value, dict) or not value:
        raise TenantAuthorizationError("OIDC tenant-role binding is required")

    bindings: dict[str, frozenset[str]] = {}
    for tenant_id, raw_roles in value.items():
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantAuthorizationError("OIDC tenant-role binding has an invalid tenant")
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        if not isinstance(raw_roles, list | tuple | set | frozenset) or any(
            not isinstance(role, str) or not role.strip() for role in raw_roles
        ):
            raise TenantAuthorizationError(
                f"OIDC tenant-role binding has invalid roles for tenant {tenant_id}"
            )
        roles = {role for role in raw_roles if role.strip()}
        if not roles:
            raise TenantAuthorizationError(
                f"OIDC tenant-role binding is missing roles for tenant {tenant_id}"
            )
        bindings[tenant_id] = frozenset(roles)
    return bindings
