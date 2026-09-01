"""PostgreSQL qualification for cross-analysis canonical action identity."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest


pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "backend" / "db" / "migrations"
MIGRATION_NAMES = tuple(
    f"{number:03d}_{name}.sql"
    for number, name in (
        (1, "authoritative_entities"),
        (2, "tenant_isolation"),
        (3, "batch_b_integrity"),
        (4, "final_gate_integrity"),
        (5, "provider_correlation_authority"),
        (6, "provider_correlation_schema"),
        (7, "model_analysis_runs"),
        (8, "model_analysis_runtime_grants"),
        (9, "model_analysis_terminal_outcomes"),
        (10, "canonical_action_identity"),
    )
)


def _database_url() -> str:
    value = os.getenv("RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL")
    if not value:
        pytest.skip(
            "RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL is required for PostgreSQL MAJOR-2 validation"
        )
    return value


def _apply_migrations(connection: object, *, include_canonical: bool = True) -> None:
    names = MIGRATION_NAMES if include_canonical else MIGRATION_NAMES[:-1]
    connection.execute("SET LOCAL search_path TO public")
    for name in names:
        connection.execute((MIGRATIONS / name).read_text(encoding="utf-8"))


def _seed(connection: object) -> tuple[str, str, str]:
    suffix = uuid4().hex
    tenant_id = f"major2-tenant-{suffix}"
    incident_id = f"major2-incident-{suffix}"
    case_id = f"major2-case-{suffix}"
    connection.execute(
        "INSERT INTO public.tenants (tenant_id, display_name) VALUES (%s, %s)",
        (tenant_id, tenant_id),
    )
    connection.execute(
        """
        INSERT INTO public.incidents (
            tenant_id, incident_id, source, received_at, correlation_key,
            intake_status, deduplication_identity
        ) VALUES (%s, %s, 'major-2-test', '2026-09-01T10:00:00Z', %s, 'accepted', %s)
        """,
        (tenant_id, incident_id, f"correlation-{suffix}", f"dedupe-{suffix}"),
    )
    connection.execute(
        """
        INSERT INTO public.cases (tenant_id, case_id, incident_id, current_state)
        VALUES (%s, %s, %s, 'timeline_ready')
        """,
        (tenant_id, case_id, incident_id),
    )
    return tenant_id, incident_id, case_id


def _insert_model_run(
    connection: object, tenant_id: str, case_id: str, analysis_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO public.model_runs (
            tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
            mode, replay_label, request_schema_version, request_checksum,
            deterministic_analysis_checksum, deterministic_exposure_checksum,
            exposure_version, exposure_currency, gross_exposure_minor,
            recoverable_value_minor, contained_value_minor,
            legitimate_value_disrupted_minor, irreversible_loss_minor,
            remaining_exposure_minor, provenance
        ) VALUES (
            %s, %s, %s, %s, %s, 'deterministic_only', 'deterministic_only',
            '1.0.0', repeat('a', 64), repeat('b', 64), repeat('c', 64),
            'exposure-v1.0.0', 'INR', 100, 80, 20, 0, 20, 60, '{}'::jsonb
        )
        """,
        (
            tenant_id,
            analysis_id,
            case_id,
            f"correlation-{analysis_id}",
            f"seed-{analysis_id}",
        ),
    )


def _insert_occurrence(
    connection: object,
    tenant_id: str,
    case_id: str,
    analysis_id: str,
    supplied_key: str,
    canonical_action_id: str,
) -> None:
    proposal = {
        "tenant_id": tenant_id,
        "case_id": case_id,
        "analysis_id": analysis_id,
        "proposal_id": f"proposal-{analysis_id}",
        "idempotency_key": supplied_key,
    }
    validation = {
        "canonical_action_identity": canonical_action_id,
        "supplied_idempotency_key": supplied_key,
    }
    connection.execute(
        """
        INSERT INTO public.model_run_proposals (
            tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
            validation_status, validation_version, validation_checksum,
            authoritative_input_checksum, policy_evaluation_ready, proposal,
            validation, canonical_action_id
        ) VALUES (
            %s, %s, %s, %s, repeat('d', 64), 'valid', 'validator-v1',
            repeat('e', 64), repeat('f', 64), true, %s::jsonb, %s::jsonb, %s
        )
        """,
        (
            tenant_id,
            analysis_id,
            case_id,
            proposal["proposal_id"],
            json.dumps(proposal, sort_keys=True),
            json.dumps(validation, sort_keys=True),
            canonical_action_id,
        ),
    )


def test_cross_analysis_writers_share_one_canonical_action_under_postgres_race() -> (
    None
):
    """Two concurrent analysis writers retain two occurrences and one identity."""

    psycopg = pytest.importorskip("psycopg")
    database_url = _database_url()
    admin = psycopg.connect(database_url)
    seed: tuple[str, str, str] | None = None
    try:
        admin.execute("BEGIN")
        _apply_migrations(admin)
        seed = _seed(admin)
        admin.commit()
        tenant_id, _, case_id = seed
        canonical_action_id = "a" * 64
        barrier = Barrier(2)

        def writer(analysis_id: str, supplied_key: str) -> bool:
            connection = psycopg.connect(database_url)
            try:
                connection.execute("BEGIN")
                connection.execute("SET LOCAL search_path TO public")
                connection.execute(
                    "SELECT set_config('reclaim.tenant_id', %s, true)", (tenant_id,)
                )
                barrier.wait(timeout=15)
                canonical_row = connection.execute(
                    """
                    INSERT INTO public.canonical_actions (
                        tenant_id, canonical_action_id, case_id
                    ) VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING canonical_action_id
                    """,
                    (tenant_id, canonical_action_id, case_id),
                ).fetchone()
                _insert_model_run(connection, tenant_id, case_id, analysis_id)
                _insert_occurrence(
                    connection,
                    tenant_id,
                    case_id,
                    analysis_id,
                    supplied_key,
                    canonical_action_id,
                )
                connection.commit()
                return canonical_row is not None
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    writer,
                    ("analysis-a", "analysis-b"),
                    ("alpha", "beta"),
                )
            )

        assert sorted(results) == [False, True]
        assert admin.execute(
            """
            SELECT count(*), count(DISTINCT canonical_action_id)
            FROM public.canonical_actions
            WHERE tenant_id = %s AND canonical_action_id = %s
            """,
            (tenant_id, canonical_action_id),
        ).fetchone() == (1, 1)
        assert admin.execute(
            """
            SELECT count(*)
            FROM public.model_run_proposals
            WHERE tenant_id = %s AND canonical_action_id = %s
            """,
            (tenant_id, canonical_action_id),
        ).fetchone() == (2,)
        assert admin.execute(
            """
            SELECT array_agg(validation ->> 'supplied_idempotency_key' ORDER BY analysis_id)
            FROM public.model_run_proposals
            WHERE tenant_id = %s AND canonical_action_id = %s
            """,
            (tenant_id, canonical_action_id),
        ).fetchone() == (["alpha", "beta"],)
    finally:
        admin.rollback()
        if seed is not None:
            admin.execute("BEGIN")
            tenant_id, incident_id, case_id = seed
            admin.execute(
                "DELETE FROM public.model_run_proposals WHERE tenant_id = %s",
                (tenant_id,),
            )
            admin.execute(
                "DELETE FROM public.canonical_actions WHERE tenant_id = %s",
                (tenant_id,),
            )
            admin.execute(
                "DELETE FROM public.model_runs WHERE tenant_id = %s", (tenant_id,)
            )
            admin.execute("DELETE FROM public.cases WHERE tenant_id = %s", (tenant_id,))
            admin.execute(
                "DELETE FROM public.incidents WHERE tenant_id = %s", (tenant_id,)
            )
            admin.execute(
                "DELETE FROM public.tenants WHERE tenant_id = %s", (tenant_id,)
            )
            admin.commit()
        admin.close()


def test_migration_010_fresh_upgrade_is_idempotent() -> None:
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(_database_url())
    try:
        connection.execute("BEGIN")
        _apply_migrations(connection)
        connection.execute(
            (MIGRATIONS / "010_canonical_action_identity.sql").read_text()
        )
        assert connection.execute(
            "SELECT to_regclass('public.canonical_actions'), "
            "to_regclass('reclaim.canonical_actions')"
        ).fetchone() == ("canonical_actions", None)
    finally:
        connection.rollback()
        connection.close()


def test_migration_010_refuses_unsafe_historical_rows() -> None:
    psycopg = pytest.importorskip("psycopg")
    database_url = _database_url()
    connection = psycopg.connect(database_url)
    seed: tuple[str, str, str] | None = None
    try:
        if connection.execute(
            "SELECT to_regclass('public.canonical_actions')"
        ).fetchone()[0]:
            pytest.skip(
                "historical-row upgrade test requires a database before migration 010"
            )
        connection.execute("BEGIN")
        _apply_migrations(connection, include_canonical=False)
        seed = _seed(connection)
        tenant_id, _, case_id = seed
        _insert_model_run(connection, tenant_id, case_id, "historical-analysis")
        connection.execute(
            """
            INSERT INTO public.model_run_proposals (
                tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                validation_status, validation_version, validation_checksum,
                authoritative_input_checksum, policy_evaluation_ready, proposal,
                validation
            ) VALUES (%s, 'historical-analysis', %s, 'historical-proposal',
                      repeat('a', 64), 'valid', 'validator-v1', repeat('b', 64),
                      repeat('c', 64), true, '{}'::jsonb, '{}'::jsonb)
            """,
            (tenant_id, case_id),
        )
        connection.commit()
        connection.execute("BEGIN")
        with pytest.raises(psycopg.Error, match="cannot safely backfill|unsafe"):
            connection.execute(
                (MIGRATIONS / "010_canonical_action_identity.sql").read_text(
                    encoding="utf-8"
                )
            )
    finally:
        connection.rollback()
        if seed is not None:
            connection.execute("BEGIN")
            tenant_id, incident_id, case_id = seed
            connection.execute(
                "DELETE FROM public.model_run_proposals WHERE tenant_id = %s",
                (tenant_id,),
            )
            connection.execute(
                "DELETE FROM public.model_runs WHERE tenant_id = %s", (tenant_id,)
            )
            connection.execute(
                "DELETE FROM public.cases WHERE tenant_id = %s", (tenant_id,)
            )
            connection.execute(
                "DELETE FROM public.incidents WHERE tenant_id = %s", (tenant_id,)
            )
            connection.execute(
                "DELETE FROM public.tenants WHERE tenant_id = %s", (tenant_id,)
            )
            connection.commit()
        connection.close()
