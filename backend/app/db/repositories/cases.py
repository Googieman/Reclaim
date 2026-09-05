"""Case repository; workflow identity is metadata, not business authority."""

from __future__ import annotations

import json
from collections.abc import Sequence
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

    def transition_terminal(
        self,
        *,
        case_id: str,
        new_state: str,
        escalation_owner: str | None = None,
    ) -> object:
        """Atomically persist one of the three explicit terminal outcomes."""

        if new_state not in {"verified_contained", "verified_failed", "escalated_unresolved"}:
            raise ValueError("case terminal state is unsupported")
        row = self.fetch_one(
            """
            UPDATE public.cases
            SET current_state = %s, escalation_owner = COALESCE(%s, escalation_owner),
                terminal_at = now(), updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
              AND current_state IN ('action_pending', 'containing')
            RETURNING tenant_id, case_id, incident_id, current_state, escalation_owner,
                      workflow_id, created_at, updated_at, terminal_at
            """,
            (new_state, escalation_owner, self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            raise ValueError("case is missing, already terminal, or not in containment")
        return row

    def mark_analyzed(self, *, case_id: str) -> object:
        """Advance a timeline-ready case to the deterministic analysis boundary."""

        row = self.fetch_one(
            """
            UPDATE public.cases
            SET current_state = 'analyzed', updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
              AND current_state IN ('timeline_ready', 'analyzed')
            RETURNING tenant_id, case_id, incident_id, current_state, escalation_owner,
                      workflow_id, created_at, updated_at, terminal_at
            """,
            (self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            raise ValueError("case is not ready for analysis")
        return row

    def mark_containing(self, *, case_id: str) -> object:
        """Enter containment only after policy/approval and gateway validation."""

        row = self.fetch_one(
            """
            UPDATE public.cases
            SET current_state = 'containing', updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
              AND current_state IN ('analyzed', 'action_pending', 'containing')
            RETURNING tenant_id, case_id, incident_id, current_state, escalation_owner,
                      workflow_id, created_at, updated_at, terminal_at
            """,
            (self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            raise ValueError("case is not ready for containment")
        return row

    def mark_action_pending(self, *, case_id: str) -> object:
        """Record that an approved action is awaiting gateway submission."""

        row = self.fetch_one(
            """
            UPDATE public.cases
            SET current_state = 'action_pending', updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
              AND current_state IN ('analyzed', 'action_pending')
            RETURNING tenant_id, case_id, incident_id, current_state, escalation_owner,
                      workflow_id, created_at, updated_at, terminal_at
            """,
            (self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            raise ValueError("case is not ready for an action")
        return row

    def set_timeline_uncertainty(self, *, case_id: str, uncertainty: Sequence[str]) -> object:
        """Persist the canonical case-level uncertainty for the current timeline."""

        values = tuple(sorted(set(uncertainty)))
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("timeline uncertainty values must be non-blank strings")
        row = self.fetch_one(
            """
            UPDATE cases
            SET timeline_uncertainty = %s::jsonb, updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
            RETURNING tenant_id, case_id, incident_id, current_state, workflow_id,
                      created_at, updated_at, terminal_at
            """,
            (
                json.dumps(values, separators=(",", ":")),
                self.tenant_context.tenant_id,
                case_id,
            ),
        )
        if row is None:
            raise ValueError("case does not exist")
        return row

    def timeline_uncertainty(self, *, case_id: str) -> tuple[str, ...] | None:
        """Read the authoritative case-level uncertainty for a timeline."""

        row = self.fetch_one(
            """
            SELECT timeline_uncertainty
            FROM cases
            WHERE tenant_id = %s AND case_id = %s
            """,
            (self.tenant_context.tenant_id, case_id),
        )
        if row is None:
            return None
        value = row[0]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("persisted timeline uncertainty is not a string array")
        return tuple(sorted(set(value)))
