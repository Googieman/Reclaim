"""Application service for the tenant-scoped operator case inbox."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from packages.contracts.case_inbox import CaseInboxItem, CaseInboxPage, OrchestrationSummary

from app.auth.oidc import RequiredRole, TenantAuthorizationContext


class CaseInboxError(ValueError):
    """Raised for invalid cursor/filter input at the inbox boundary."""


class CaseInboxService:
    """Build a read model from PostgreSQL without searching narrative content."""

    ALLOWED_CASE_STATES = frozenset(
        {
            "intake_received",
            "collecting_evidence",
            "timeline_ready",
            "analyzed",
            "action_pending",
            "containing",
            "verified_contained",
            "verified_failed",
            "escalated_unresolved",
        }
    )
    ALLOWED_AUTOMATION_STATUSES = frozenset(
        {"queued", "running", "awaiting_human", "completed", "failed", "requires_attention"}
    )

    def __init__(self, *, unit_of_work_factory: Any) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def list_cases(
        self,
        *,
        authorization_context: TenantAuthorizationContext,
        correlation_id: str,
        state: str | None = None,
        automation_status: str | None = None,
        query: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> CaseInboxPage:
        authorization_context.require_role(RequiredRole.REVIEWER)
        if not correlation_id.strip():
            raise CaseInboxError("correlation_id is required")
        if not 1 <= limit <= 100:
            raise CaseInboxError("limit must be between 1 and 100")
        if query is not None and len(query) > 100:
            raise CaseInboxError("identifier query is too long")
        if state is not None and state not in self.ALLOWED_CASE_STATES:
            raise CaseInboxError("case state filter is not allowlisted")
        if (
            automation_status is not None
            and automation_status not in self.ALLOWED_AUTOMATION_STATUSES
        ):
            raise CaseInboxError("automation status filter is not allowlisted")
        decoded_cursor = decode_cursor(cursor) if cursor else None
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            rows = unit_of_work.case_inbox.page(
                state=state,
                automation_status=automation_status,
                query=query.strip() if query else None,
                cursor=decoded_cursor,
                limit=limit,
            )
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = encode_cursor(visible[-1].updated_at, visible[-1].case_id)
        return CaseInboxPage(
            tenant_id=authorization_context.tenant_id,
            correlation_id=correlation_id,
            items=[_item(row) for row in visible],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
        )


def encode_cursor(updated_at: datetime, case_id: str) -> str:
    if updated_at.tzinfo is None or updated_at.utcoffset() is None:
        raise CaseInboxError("cursor timestamp must include timezone")
    payload = {
        "updated_at": updated_at.astimezone(UTC).isoformat(),
        "case_id": case_id,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, str]:
    if not value.strip() or len(value) > 512:
        raise CaseInboxError("cursor is invalid")
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        moment = datetime.fromisoformat(str(payload["updated_at"]))
        case_id = str(payload["case_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CaseInboxError("cursor is invalid") from exc
    if moment.tzinfo is None or moment.utcoffset() is None or not case_id.strip():
        raise CaseInboxError("cursor is invalid")
    return moment.astimezone(UTC), case_id


def _item(row: Any) -> CaseInboxItem:
    orchestration = None
    if row.orchestration is not None:
        run = row.orchestration
        orchestration = OrchestrationSummary(
            run_id=str(run[0]),
            workflow_version=str(run[1]),
            external_execution_id=str(run[2]),
            stage=str(run[3]),
            status=str(run[4]),
            queued_at=run[5],
            started_at=run[6],
            completed_at=run[7],
            updated_at=run[8],
            failure_code=None if run[9] is None else str(run[9]),
        )
    identifiers = {
        key: value
        for key, value in {
            "customer_reference": row.customer_reference,
            "account_reference": row.account_reference,
            "order_reference": row.order_reference,
            "payment_reference": row.payment_reference,
        }.items()
        if value
    }
    occurred_at = row.occurred_at or row.created_at
    return CaseInboxItem(
        tenant_id=row.tenant_id,
        case_id=row.case_id,
        incident_id=row.incident_id,
        merchant_name=row.merchant_name or row.tenant_id,
        source=row.source,
        incident_type=row.incident_type or "other",
        occurred_at=occurred_at,
        state=row.state,
        updated_at=row.updated_at,
        created_at=row.created_at,
        identifiers=identifiers,
        reported_amount_minor=row.reported_amount_minor,
        reported_currency=row.reported_currency,
        external_reference=row.external_reference,
        orchestration=orchestration,
    )


__all__ = ["CaseInboxError", "CaseInboxService", "decode_cursor", "encode_cursor"]
