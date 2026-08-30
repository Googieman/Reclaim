"""Case repository; workflow identity is metadata, not business authority."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class CaseRepository(TenantScopedRepository):
    _STATE_TRANSITIONS = {
        "intake_received": {"collecting_evidence", "timeline_ready"},
        "collecting_evidence": {"collecting_evidence", "timeline_ready"},
        "timeline_ready": {"timeline_ready"},
    }

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

    def find_by_incident_id(self, *, incident_id: str) -> object | None:
        if not incident_id.strip():
            raise ValueError("incident_id is required")
        return self.fetch_one(
            """
            SELECT tenant_id, case_id, incident_id, current_state, workflow_id,
                   created_at, updated_at, terminal_at
            FROM cases
            WHERE tenant_id = %s AND incident_id = %s
            """,
            (self.tenant_context.tenant_id, incident_id),
        )

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

    def bind_workflow(self, *, case_id: str, workflow_id: str) -> object:
        """Persist deterministic workflow metadata without changing case state."""

        if not workflow_id.strip():
            raise ValueError("workflow_id is required")
        row = self.fetch_one(
            """
            UPDATE cases
            SET workflow_id = COALESCE(workflow_id, %s), updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
              AND (workflow_id IS NULL OR workflow_id = %s)
            RETURNING tenant_id, case_id, incident_id, current_state, workflow_id,
                      created_at, updated_at, terminal_at
            """,
            (
                workflow_id,
                self.tenant_context.tenant_id,
                case_id,
                workflow_id,
            ),
        )
        if row is None:
            raise ValueError("case does not exist or is bound to another workflow")
        return row

    def transition_state(self, *, case_id: str, new_state: str) -> object:
        """Advance only the evidence/timeline states through an explicit transition."""

        if new_state not in {
            "intake_received",
            "collecting_evidence",
            "timeline_ready",
        }:
            raise ValueError("case state transition is outside the evidence/timeline boundary")
        current = self.get(case_id=case_id)
        if current is None:
            raise ValueError("case does not exist")
        current_state = str(current[3])
        if new_state not in self._STATE_TRANSITIONS.get(current_state, set()):
            raise ValueError(f"case cannot transition from {current_state} to {new_state}")
        row = self.fetch_one(
            """
            UPDATE cases
            SET current_state = %s, updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
            RETURNING tenant_id, case_id, incident_id, current_state, workflow_id,
                      created_at, updated_at, terminal_at
            """,
            (new_state, self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            raise RuntimeError("case state transition returned no row")
        return row
