"""Tenant context propagation for PostgreSQL row-level security."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
    """A transaction-local tenant context consumed by PostgreSQL RLS policies."""

    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", require_tenant_id(self.tenant_id))

    def apply(self, connection: ExecutableConnection) -> None:
        """Set the transaction-local PostgreSQL setting used by RLS."""

        connection.execute(
            "SELECT set_config('reclaim.tenant_id', %s, true)",
            (self.tenant_id,),
        )
