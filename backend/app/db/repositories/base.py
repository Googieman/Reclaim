"""Small, explicit repository primitives over a PostgreSQL connection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.db.tenant_context import TenantContext


class RepositoryError(RuntimeError):
    """Raised for repository misuse that must not be silently recovered."""


class Connection(Protocol):
    def execute(self, query: str, params: Sequence[object] = ()) -> Any: ...


class TenantScopedRepository:
    """Base for repositories that can only operate inside one tenant context."""

    def __init__(self, connection: Connection, tenant_context: TenantContext) -> None:
        self.connection = connection
        self.tenant_context = tenant_context

    def execute(self, query: str, params: Sequence[object] = ()) -> Any:
        if not self.tenant_context.tenant_id:
            raise RepositoryError("repository requires tenant context")
        return self.connection.execute(query, params)

    def assert_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_context.tenant_id:
            raise RepositoryError("repository tenant does not match transaction context")

    def fetch_one(self, query: str, params: Sequence[object] = ()) -> Any | None:
        cursor = self.execute(query, params)
        return cursor.fetchone()

    def fetch_all(self, query: str, params: Sequence[object] = ()) -> list[Any]:
        cursor = self.execute(query, params)
        return list(cursor.fetchall())
