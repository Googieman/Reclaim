"""Case repository; workflow identity is metadata, not business authority."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class CaseRepository(TenantScopedRepository):
    def create(
        self,
        *,
        case_id: str,
        incident_id: str,
        current_state: str = "intake_received",
        workflow_id: str | None = None,
        created_at: datetime | None = None,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO cases (
                tenant_id, case_id, incident_id, current_state, workflow_id,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), COALESCE(%s, now()))
            RETURNING tenant_id, case_id, incident_id, current_state, workflow_id,
                      created_at, updated_at, terminal_at
            """,
            (
                self.tenant_context.tenant_id,
                case_id,
                incident_id,
                current_state,
                workflow_id,
                created_at,
                created_at,
            ),
        )
        if row is None:
            raise RuntimeError("case insert returned no row")
        return row

    def get(self, *, case_id: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, case_id, incident_id, current_state, escalation_owner,
                   workflow_id, created_at, updated_at, terminal_at
            FROM cases
            WHERE tenant_id = %s AND case_id = %s
            """,
            (self.tenant_context.tenant_id, case_id),
        )
