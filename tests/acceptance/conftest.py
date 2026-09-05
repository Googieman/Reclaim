"""Acceptance fixtures for live authoritative intake and US1 runtime stages."""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.intake.service import IncidentIntakeService
from app.storage.minio_evidence import ImmutableEvidenceStore


@pytest.fixture
def t153_config() -> Any:
    """Require the explicit prepared T153 stack; never substitute a fake runtime."""

    from support.t153_runtime import require_t153_config

    return require_t153_config()


@pytest.fixture
def postgres_intake_service() -> IncidentIntakeService:
    """Build the real PostgreSQL intake service when a live URL is configured."""

    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not database_url:
        pytest.skip("RECLAIM_DATABASE_URL is required for canonical intake validation")

    import psycopg
    from app.db.unit_of_work import PostgresUnitOfWork
    raw_report_store = _raw_report_store()

    return IncidentIntakeService(
        unit_of_work_factory=lambda authorization_context: PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=authorization_context,
        ),
        raw_report_store=raw_report_store,
    )


def _unit_of_work_factory() -> Any:
    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not database_url:
        pytest.skip("RECLAIM_DATABASE_URL is required for acceptance")
    import psycopg
    from app.db.unit_of_work import PostgresUnitOfWork

    return lambda authorization_context: PostgresUnitOfWork(
        lambda: psycopg.connect(database_url),
        authorization_context=authorization_context,
    )


def _evidence_storage() -> Any:
    from evidence.storage import EvidenceStorage

    endpoint = os.getenv("RECLAIM_MINIO_ENDPOINT")
    access_key = os.getenv("RECLAIM_MINIO_ACCESS_KEY")
    secret_key = os.getenv("RECLAIM_MINIO_SECRET_KEY")
    if not (endpoint and access_key and secret_key):
        pytest.skip(
            "live MinIO endpoint, access key, and secret key are required for acceptance"
        )
    store = ImmutableEvidenceStore.from_endpoint(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
    )
    return EvidenceStorage(store)


def _raw_report_store() -> ImmutableEvidenceStore:
    """Require the live immutable evidence store for acceptance tests."""

    endpoint = os.getenv("RECLAIM_MINIO_ENDPOINT")
    access_key = os.getenv("RECLAIM_MINIO_ACCESS_KEY")
    secret_key = os.getenv("RECLAIM_MINIO_SECRET_KEY")
    if not (endpoint and access_key and secret_key):
        pytest.skip(
            "live MinIO endpoint, access key, and secret key are required for acceptance"
        )
    return ImmutableEvidenceStore.from_endpoint(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
    )


def _evidence_orchestrator(tenant_id: str) -> Any:
    """Build the production orchestrator against the live evidence store."""

    from connectors.simulators.evidence import build_default_evidence_simulators
    from evidence.orchestrator import EvidenceOrchestrator

    return EvidenceOrchestrator(
        build_default_evidence_simulators(tenant_id),
        storage=_evidence_storage(),
        unit_of_work_factory=_unit_of_work_factory(),
    )


@pytest.fixture
def t043_evidence_orchestrator() -> Any:
    """Build the legacy US1 fixture with its historical tenant scope."""

    return _evidence_orchestrator("tenant-a")


@pytest.fixture
def t153_evidence_orchestrator() -> Any:
    """Build the T153 fixture with the canonical tenant scope."""

    return _evidence_orchestrator("tenant-canonical-demo")


@pytest.fixture
def timeline_reconstructor() -> Any:
    """Build deterministic timeline reconstruction with optional live persistence."""

    from timeline.reconstruct import TimelineReconstructor

    return TimelineReconstructor(unit_of_work_factory=_unit_of_work_factory())
