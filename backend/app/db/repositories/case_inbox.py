"""Narrative-free cursor pagination for the operator case inbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .base import RepositoryError, TenantScopedRepository


@dataclass(frozen=True, slots=True)
class CaseInboxRecord:
    tenant_id: str
    case_id: str
    incident_id: str
    state: str
    created_at: datetime
    updated_at: datetime
    source: str
    incident_type: str | None
    occurred_at: datetime | None
    customer_reference: str | None
    account_reference: str | None
    order_reference: str | None
    payment_reference: str | None
    reported_amount_minor: int | None
    reported_currency: str | None
    external_reference: str | None
    merchant_name: str | None
    orchestration: tuple[Any, ...] | None


class CaseInboxRepository(TenantScopedRepository):
    """Query only identifiers and typed intake fields; narrative is excluded."""

    def page(
        self,
        *,
        state: str | None,
        automation_status: str | None,
        query: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> list[CaseInboxRecord]:
        if not 1 <= limit <= 100:
            raise RepositoryError("inbox limit must be between 1 and 100")
        clauses = ["c.tenant_id = %s"]
        params: list[object] = [self.tenant_context.tenant_id]
        if state:
            clauses.append("c.current_state = %s")
            params.append(state)
        if automation_status:
            clauses.append("latest.status = %s")
            params.append(automation_status)
        if query:
            clauses.append(
                "("
                "c.case_id ILIKE %s OR c.incident_id ILIKE %s "
                "OR i.customer_reference ILIKE %s OR i.account_reference ILIKE %s "
                "OR i.order_reference ILIKE %s OR i.payment_reference ILIKE %s "
                "OR i.external_reference ILIKE %s)"
            )
            term = f"%{query}%"
            params.extend([term] * 7)
        if cursor is not None:
            clauses.append("(c.updated_at, c.case_id) < (%s, %s)")
            params.extend(cursor)
        params.append(limit + 1)
        rows = self.fetch_all(
            f"""
            SELECT c.tenant_id, c.case_id, c.incident_id, c.current_state,
                   c.created_at, c.updated_at,
                   i.source, i.incident_type, i.occurred_at,
                   i.customer_reference, i.account_reference, i.order_reference,
                   i.payment_reference, i.reported_amount_minor,
                   i.reported_currency, i.external_reference,
                   t.display_name,
                   latest.run_id, latest.workflow_version,
                   latest.external_execution_id, latest.stage, latest.status,
                   latest.queued_at, latest.started_at, latest.completed_at,
                   latest.updated_at, latest.failure_code
            FROM public.cases AS c
            JOIN public.incidents AS i
              ON i.tenant_id = c.tenant_id AND i.incident_id = c.incident_id
            JOIN public.tenants AS t ON t.tenant_id = c.tenant_id
            LEFT JOIN LATERAL (
                SELECT r.run_id, r.workflow_version, r.external_execution_id,
                       r.stage, r.status, r.queued_at, r.started_at,
                       r.completed_at, r.updated_at, r.failure_code
                FROM public.orchestration_runs AS r
                WHERE r.tenant_id = c.tenant_id AND r.case_id = c.case_id
                ORDER BY r.updated_at DESC, r.run_id DESC
                LIMIT 1
            ) AS latest ON TRUE
            WHERE {' AND '.join(clauses)}
            ORDER BY c.updated_at DESC, c.case_id DESC
            LIMIT %s
            """,
            params,
        )
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: Any) -> CaseInboxRecord:
        latest = tuple(row[17:27]) if row[17] is not None else None
        return CaseInboxRecord(
            tenant_id=str(row[0]),
            case_id=str(row[1]),
            incident_id=str(row[2]),
            state=str(row[3]),
            created_at=row[4],
            updated_at=row[5],
            source=str(row[6]),
            incident_type=None if row[7] is None else str(row[7]),
            occurred_at=row[8],
            customer_reference=None if row[9] is None else str(row[9]),
            account_reference=None if row[10] is None else str(row[10]),
            order_reference=None if row[11] is None else str(row[11]),
            payment_reference=None if row[12] is None else str(row[12]),
            reported_amount_minor=None if row[13] is None else int(row[13]),
            reported_currency=None if row[14] is None else str(row[14]).strip(),
            external_reference=None if row[15] is None else str(row[15]),
            merchant_name=None if row[16] is None else str(row[16]),
            orchestration=latest,
        )


__all__ = ["CaseInboxRecord", "CaseInboxRepository"]
