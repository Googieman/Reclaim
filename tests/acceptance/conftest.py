"""Acceptance fixtures for live authoritative intake and US1 runtime stages."""

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


def _unit_of_work_factory() -> Any | None:
    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not database_url:
        return None
    import psycopg
    from app.db.unit_of_work import PostgresUnitOfWork

    return lambda authorization_context: PostgresUnitOfWork(
        lambda: psycopg.connect(database_url),
        authorization_context=authorization_context,
    )


def _evidence_storage() -> Any:
    from app.storage.minio_evidence import ImmutableEvidenceStore
    from evidence.storage import EvidenceStorage, InMemoryObjectStorage

    endpoint = os.getenv("RECLAIM_MINIO_ENDPOINT")
    access_key = os.getenv("RECLAIM_MINIO_ACCESS_KEY")
    secret_key = os.getenv("RECLAIM_MINIO_SECRET_KEY")
    if endpoint and access_key and secret_key:
        store = ImmutableEvidenceStore.from_endpoint(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
        )
    else:
        store = ImmutableEvidenceStore(InMemoryObjectStorage())
    return EvidenceStorage(store)


@pytest.fixture
def evidence_orchestrator() -> Any:
    """Build the production orchestrator with a test/replay object store when needed."""

    from connectors.simulators.evidence import build_default_evidence_simulators
    from evidence.orchestrator import EvidenceOrchestrator

    return EvidenceOrchestrator(
        build_default_evidence_simulators("tenant-a"),
        storage=_evidence_storage(),
        unit_of_work_factory=_unit_of_work_factory(),
    )


@pytest.fixture
def timeline_reconstructor() -> Any:
    """Build deterministic timeline reconstruction with optional live persistence."""

    from timeline.reconstruct import TimelineReconstructor

    return TimelineReconstructor(unit_of_work_factory=_unit_of_work_factory())
