"""OIDC identity verification and tenant-aware role checks."""

from .oidc import (
    AuthenticatedPrincipal,
    IdentityType,
    OIDCVerifier,
    RequiredRole,
    TenantAuthorizationError,
)

__all__ = [
    "AuthenticatedPrincipal",
    "IdentityType",
    "OIDCVerifier",
    "RequiredRole",
    "TenantAuthorizationError",
]
