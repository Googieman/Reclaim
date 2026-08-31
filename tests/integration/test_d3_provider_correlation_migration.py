"""Fresh migration regression for D3 schema placement."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "backend" / "db" / "migrations"


def test_d3_migration_is_independent_of_migration_role_search_path() -> None:
    database_url = os.getenv("RECLAIM_D3_MIGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "RECLAIM_D3_MIGRATION_DATABASE_URL is required for fresh migration validation"
        )

    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(database_url)
    try:
        connection.execute("BEGIN")
        connection.execute("SET LOCAL search_path TO public")
        for migration_name in (
            "001_authoritative_entities.sql",
            "002_tenant_isolation.sql",
            "003_batch_b_integrity.sql",
            "004_final_gate_integrity.sql",
        ):
            connection.execute(
                (MIGRATIONS / migration_name).read_text(encoding="utf-8")
            )

        # Reproduce the failed release setup: only the D3 migration role's
        # search_path changes, while the existing authoritative tables remain
        # in public.
        connection.execute("SET LOCAL search_path TO reclaim, public")
        connection.execute(
            (MIGRATIONS / "005_provider_correlation_authority.sql").read_text(
                encoding="utf-8"
            )
        )
        assert connection.execute(
            """
            SELECT namespace.nspname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE relation.relname = 'provider_correlation_mappings'
            ORDER BY namespace.nspname
            """
        ).fetchall() == [("reclaim",)]

        corrective_migration = (
            MIGRATIONS / "006_provider_correlation_schema.sql"
        ).read_text(encoding="utf-8")
        connection.execute(corrective_migration)
        connection.execute(corrective_migration)

        assert connection.execute(
            """
            SELECT namespace.nspname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE relation.relname = 'provider_correlation_mappings'
            ORDER BY namespace.nspname
            """
        ).fetchall() == [("public",)]
        assert connection.execute(
            "SELECT to_regclass('reclaim.provider_correlation_mappings')"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT to_regclass('public.provider_correlation_mappings') IS NOT NULL"
        ).fetchone() == (True,)
    finally:
        connection.rollback()
        connection.close()
