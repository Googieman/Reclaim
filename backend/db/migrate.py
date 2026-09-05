"""Transactional, checksum-verified PostgreSQL migration runner.

The migration runner is a deployment concern.  Application services must not run
migrations at startup, and ``--check`` intentionally performs no writes.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIGRATION_DIRECTORY = Path(__file__).resolve().parent / "migrations"
MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]+)_(?P<name>[a-z0-9][a-z0-9_-]*)\.sql$")
MIGRATION_LOCK_KEY = 814_006_014
LEDGER_TABLE = "public.schema_migrations"


class MigrationError(RuntimeError):
    """Raised when migration discovery or validation cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True, slots=True)
class MigrationCheck:
    pending: tuple[str, ...]
    checksum_mismatches: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.pending and not self.checksum_mismatches


@dataclass(frozen=True, slots=True)
class MigrationApply:
    applied: tuple[str, ...]


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    """Load numbered SQL files in deterministic order with content checksums."""

    if not directory.is_dir():
        raise MigrationError(f"migration directory does not exist: {directory}")
    discovered: list[Migration] = []
    seen: set[str] = set()
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            continue
        version = match.group("version")
        if version in seen:
            raise MigrationError(f"duplicate migration version {version}")
        seen.add(version)
        sql = path.read_text(encoding="utf-8")
        checksum = "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()
        discovered.append(Migration(version, match.group("name"), path, checksum, sql))
    return tuple(sorted(discovered, key=lambda item: (int(item.version), item.version)))


def migration_files(directory: Path = MIGRATION_DIRECTORY) -> tuple[Path, ...]:
    """Return migration paths in the same order used by the canonical runner."""

    return tuple(item.path for item in discover_migrations(directory))


class MigrationRunner:
    """Apply numbered migrations under one PostgreSQL advisory transaction lock."""

    def __init__(self, connection: Any, *, migration_dir: Path) -> None:
        self.connection = connection
        self.migrations = discover_migrations(migration_dir)

    def check(self) -> MigrationCheck:
        """Return pending or modified migrations without changing database state."""

        if not self._ledger_exists():
            return MigrationCheck(tuple(item.version for item in self.migrations), ())
        applied = self._read_ledger()
        mismatches = tuple(
            item.version
            for item in self.migrations
            if item.version in applied and applied[item.version] != item.checksum
        )
        pending = tuple(item.version for item in self.migrations if item.version not in applied)
        return MigrationCheck(pending, mismatches)

    def apply(self) -> MigrationApply:
        """Apply all unapplied migrations or roll back the complete attempt."""

        self.connection.execute("BEGIN")
        try:
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (MIGRATION_LOCK_KEY,),
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS public.schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            applied = self._read_ledger()
            mismatches = tuple(
                item.version
                for item in self.migrations
                if item.version in applied and applied[item.version] != item.checksum
            )
            if mismatches:
                joined = ", ".join(mismatches)
                raise MigrationError(f"checksum mismatch for migration {joined}")

            applied_now: list[str] = []
            for migration in self.migrations:
                if migration.version in applied:
                    continue
                self.connection.execute(migration.sql)
                self.connection.execute(
                    """
                    INSERT INTO public.schema_migrations (version, checksum)
                    VALUES (%s, %s)
                    """,
                    (migration.version, migration.checksum),
                )
                applied_now.append(migration.version)
            self.connection.commit()
            return MigrationApply(tuple(applied_now))
        except BaseException:
            self.connection.rollback()
            raise

    def _ledger_exists(self) -> bool:
        row = self.connection.execute("SELECT to_regclass('public.schema_migrations')").fetchone()
        return bool(row and row[0])

    def _read_ledger(self) -> dict[str, str]:
        rows = self.connection.execute(
            "SELECT version, checksum FROM public.schema_migrations ORDER BY version"
        ).fetchall()
        return {str(version): str(checksum) for version, checksum in rows}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply or check RECLAIM PostgreSQL migrations")
    parser.add_argument("--check", action="store_true", help="check without writing")
    parser.add_argument(
        "--migration-dir",
        type=Path,
        default=MIGRATION_DIRECTORY,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    import psycopg

    database_url = os.environ.get("RECLAIM_MIGRATION_DATABASE_URL") or os.environ.get(
        "RECLAIM_DATABASE_URL"
    )
    if not database_url:
        raise SystemExit("RECLAIM_MIGRATION_DATABASE_URL or RECLAIM_DATABASE_URL is required")
    with psycopg.connect(database_url) as connection:
        runner = MigrationRunner(connection, migration_dir=args.migration_dir)
        if args.check:
            result = runner.check()
            if result.pending:
                print("pending migrations: " + ", ".join(result.pending))
            if result.checksum_mismatches:
                print("checksum mismatches: " + ", ".join(result.checksum_mismatches))
            return 0 if result.ok else 1
        result = runner.apply()
        if result.applied:
            print("applied migrations: " + ", ".join(result.applied))
        return 0


if __name__ == "__main__":  # pragma: no cover - exercised by deployment smoke tests
    raise SystemExit(main())
