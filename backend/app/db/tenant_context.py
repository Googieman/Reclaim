"""Tenant context propagation for PostgreSQL row-level security."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.auth.oidc import TenantAuthorizationContext


class TenantContextError(ValueError):
    """Raised when a database operation lacks a valid tenant context."""


class ExecutableConnection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Any: ...


def require_tenant_id(tenant_id: str) -> str:
    """Return a normalized tenant ID or fail before a database call is made."""

    normalized = tenant_id.strip()
    if not normalized:
        raise TenantContextError("tenant_id is required")
    return normalized


@dataclass(frozen=True, slots=True)
class TenantContext:
    """A transaction-local tenant context derived from authenticated authorization."""

    tenant_id: str
    authorization_context: TenantAuthorizationContext

    def __post_init__(self) -> None:
        if not isinstance(self.authorization_context, TenantAuthorizationContext):
            raise TenantContextError("authenticated authorization context is required")
        normalized = require_tenant_id(self.tenant_id)
        if normalized != self.authorization_context.tenant_id:
            raise TenantContextError(
                "tenant_id does not match the authenticated authorization context"
            )
        object.__setattr__(self, "tenant_id", normalized)

    @classmethod
    def from_authorization_context(
        cls, authorization_context: TenantAuthorizationContext
    ) -> TenantContext:
        return cls(
            tenant_id=authorization_context.tenant_id,
            authorization_context=authorization_context,
        )

    def apply(self, connection: ExecutableConnection) -> None:
        """Set the transaction-local PostgreSQL setting used by RLS."""

        connection.execute(
            "SELECT set_config('reclaim.tenant_id', %s, true)",
            (self.tenant_id,),
        )
