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
        )
