"""Tenant repository; tenant rows are authoritative PostgreSQL state."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class TenantRepository(TenantScopedRepository):
    def create(
        self,
        *,
        tenant_id: str,
        display_name: str,
        status: str = "active",
        created_at: datetime | None = None,
    ) -> object:
        """Create a tenant through a parameterized authoritative write."""

        self.assert_tenant(tenant_id)
        row = self.fetch_one(
            """
            INSERT INTO tenants (tenant_id, display_name, status, created_at, updated_at)
            VALUES (%s, %s, %s, COALESCE(%s, now()), COALESCE(%s, now()))
            RETURNING tenant_id, display_name, status, created_at, updated_at
            """,
            (tenant_id, display_name, status, created_at, created_at),
        )
        if row is None:
            raise RuntimeError("tenant insert returned no row")
        return row

    def get(self, *, tenant_id: str) -> object | None:
        self.assert_tenant(tenant_id)
        return self.fetch_one(
            "SELECT tenant_id, display_name, status, created_at, updated_at FROM tenants WHERE tenant_id = %s",
            (tenant_id,),
        )
