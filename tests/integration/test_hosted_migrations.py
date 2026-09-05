"""Contract and optional live tests for the hosted migration runner."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from db.migrate import MigrationError, MigrationRunner, discover_migrations


def test_discover_migrations_is_numeric_and_checksumed(tmp_path: Path) -> None:
    (tmp_path / "010_later.sql").write_text("select 10;\n", encoding="utf-8")
    (tmp_path / "002_earlier.sql").write_text("select 2;\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == ["002", "010"]
    assert (
        migrations[0].checksum == "sha256:" + hashlib.sha256(b"select 2;\n").hexdigest()
    )


def test_discover_migrations_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "002_first.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "002_second.sql").write_text("select 2;", encoding="utf-8")

    with pytest.raises(MigrationError, match="duplicate migration version 002"):
        discover_migrations(tmp_path)


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, *, ledger_exists: bool, applied: list[tuple[str, str]]) -> None:
        self.ledger_exists = ledger_exists
        self.applied = applied
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> FakeResult:
        self.statements.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "to_regclass" in normalized:
            return FakeResult(
                [("public.schema_migrations",)] if self.ledger_exists else [(None,)]
            )
        if "select version, checksum" in normalized:
            return FakeResult(
                [(version, checksum) for version, checksum in self.applied]
            )
        if normalized.startswith("insert into public.schema_migrations"):
            assert params is not None
            self.applied.append((str(params[0]), str(params[1])))
        return FakeResult([])

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_check_is_read_only_and_reports_pending_without_creating_ledger(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_initial.sql").write_text("select 1;", encoding="utf-8")
    connection = FakeConnection(ledger_exists=False, applied=[])

    result = MigrationRunner(connection, migration_dir=tmp_path).check()

    assert result.pending == ("001",)
    assert result.checksum_mismatches == ()
    assert connection.commits == 0
    assert not any("create table" in sql.lower() for sql, _ in connection.statements)


def test_apply_locks_validates_checksum_and_records_each_migration(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_initial.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "002_next.sql").write_text("select 2;", encoding="utf-8")
    connection = FakeConnection(ledger_exists=True, applied=[])

    result = MigrationRunner(connection, migration_dir=tmp_path).apply()

    assert result.applied == ("001", "002")
    assert connection.commits == 1
    assert any("pg_advisory_xact_lock" in sql for sql, _ in connection.statements)
    assert [row[0] for row in connection.applied] == ["001", "002"]


def test_apply_rejects_modified_applied_migration(tmp_path: Path) -> None:
    migration = tmp_path / "001_initial.sql"
    migration.write_text("select changed;", encoding="utf-8")
    connection = FakeConnection(ledger_exists=True, applied=[("001", "sha256:old")])

    with pytest.raises(MigrationError, match="checksum mismatch for migration 001"):
        MigrationRunner(connection, migration_dir=tmp_path).apply()

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_hosted_roles_and_secret_audit_migration_are_least_privilege() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "db"
        / "migrations"
        / "014_hosted_service_roles.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())

    for role in (
        "reclaim_api",
        "reclaim_gateway",
        "reclaim_event_relay",
        "reclaim_projection",
        "reclaim_secret_audit",
        "reclaim_keycloak",
        "reclaim_mlflow",
    ):
        assert f"create role {role}" in normalized
        assert "grant login" not in normalized
    assert "create table if not exists public.secret_access_events" in normalized
    assert "secret_id text not null" in normalized
    assert "request_id text not null" in normalized
    assert "outcome text not null" in normalized
    assert "secret_value" not in normalized
    assert "secret_payload" not in normalized
    assert (
        "grant insert on table public.secret_access_events to reclaim_secret_audit"
        in normalized
    )
    assert "grant select on table public.secret_access_events" not in normalized
    assert "secret_access_events_append_only" in normalized


@pytest.mark.integration
def test_live_hosted_migrations_if_database_is_configured() -> None:
    database_url = __import__("os").getenv("RECLAIM_HOSTED_MIGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "RECLAIM_HOSTED_MIGRATION_DATABASE_URL is required for live migration validation"
        )
    pytest.importorskip("psycopg")
    pytest.fail("live migration rehearsal is an operator-owned deployment gate")
