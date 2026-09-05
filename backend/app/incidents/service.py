"""Authoritative incident creation and duplicate identity handling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from app.db.repositories.incidents import IncidentCreateResult
from app.db.unit_of_work import PostgresUnitOfWork


class IncidentService:
    """Create or retrieve one tenant-scoped incident identity."""

    def __init__(self, *, id_factory: Callable[[str], str]) -> None:
        self.id_factory = id_factory

    def create_or_get(
        self,
        unit_of_work: PostgresUnitOfWork,
        *,
        source: str,
        reporter_context: Mapping[str, object],
        received_at: datetime,
        correlation_key: str,
        raw_input_reference: str | None,
        intake_status: str,
        deduplication_identity: str,
        incident_type: str | None = None,
        occurred_at: datetime | None = None,
        narrative_checksum: str | None = None,
        customer_reference: str | None = None,
        account_reference: str | None = None,
        order_reference: str | None = None,
        payment_reference: str | None = None,
        reported_amount_minor: int | None = None,
        reported_currency: str | None = None,
        external_reference: str | None = None,
    ) -> IncidentCreateResult:
        if intake_status not in {"accepted", "rejected", "quarantined"}:
            raise ValueError("unsupported incident intake status")
        return unit_of_work.incidents.create_or_get(
            incident_id=self.id_factory("incident"),
            source=source,
            reporter_context=reporter_context,
            received_at=received_at,
            correlation_key=correlation_key,
            raw_input_reference=raw_input_reference,
            intake_status=intake_status,
            deduplication_identity=deduplication_identity,
            incident_type=incident_type,
            occurred_at=occurred_at,
            narrative_checksum=narrative_checksum,
            customer_reference=customer_reference,
            account_reference=account_reference,
            order_reference=order_reference,
            payment_reference=payment_reference,
            reported_amount_minor=reported_amount_minor,
            reported_currency=reported_currency,
            external_reference=external_reference,
        )
