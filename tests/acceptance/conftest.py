"""Acceptance fixtures for live authoritative intake and pending US1 stages."""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.intake.service import IncidentIntakeService


@pytest.fixture
def postgres_intake_service() -> IncidentIntakeService:
    """Build the real PostgreSQL intake service when a live URL is configured."""

    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not database_url:
        pytest.skip("RECLAIM_DATABASE_URL is required for canonical intake validation")

    import psycopg
    from app.db.unit_of_work import PostgresUnitOfWork

    return IncidentIntakeService(
        unit_of_work_factory=lambda authorization_context: PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=authorization_context,
        )
    )


@pytest.fixture
def evidence_orchestrator() -> Any | None:
    """Mark the T052 production boundary as unavailable until its task is implemented."""

    return None


@pytest.fixture
def timeline_reconstructor() -> Any | None:
    """Mark the T055 production boundary as unavailable until its task is implemented."""

    return None
