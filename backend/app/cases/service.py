"""Authoritative case creation and incident-to-case identity handling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.db.unit_of_work import PostgresUnitOfWork


class CaseService:
    """Create and retrieve a case only through the tenant-scoped UoW."""

    def __init__(self, *, id_factory: Callable[[str], str]) -> None:
        self.id_factory = id_factory

    def create(
        self,
        unit_of_work: PostgresUnitOfWork,
        *,
        incident_id: str,
        created_at: datetime,
    ) -> object:
        return unit_of_work.cases.create(
            case_id=self.id_factory("case"),
            incident_id=incident_id,
            current_state="intake_received",
            workflow_id=None,
            created_at=created_at,
        )

    def find_by_incident(
        self, unit_of_work: PostgresUnitOfWork, *, incident_id: str
    ) -> object | None:
        return unit_of_work.cases.find_by_incident_id(incident_id=incident_id)
