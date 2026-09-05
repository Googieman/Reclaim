"""Apply the authoritative PostgreSQL migrations for a deployed service."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[1] / "db" / "migrations"
MIGRATION_LOCK_KEY = "reclaim-authoritative-migrations-v1"


def migration_files(directory: Path = MIGRATION_DIRECTORY) -> tuple[Path, ...]:
    """Return numbered SQL migrations in deterministic application order."""

    return tuple(sorted(directory.glob("[0-9][0-9][0-9]_*.sql")))


def apply_migrations(
    database_url: str | None = None, *, directory: Path = MIGRATION_DIRECTORY
) -> int:
    """Apply unapplied migrations, failing closed if an applied file changes."""

    resolved_url = database_url or os.environ.get("RECLAIM_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not resolved_url:
        raise RuntimeError("RECLAIM_DATABASE_URL or DATABASE_URL is required")

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in the deployment image
        raise RuntimeError("psycopg[binary] is required to apply migrations") from exc

    migrations = migration_files(directory)
    if not migrations:
        raise RuntimeError(f"no SQL migrations found in {directory}")

    applied = 0
    with psycopg.connect(resolved_url) as connection:
        connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS public.reclaim_schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            connection.commit()

            for migration in migrations:
                checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
                row = connection.execute(
                    "SELECT checksum FROM public.reclaim_schema_migrations "
                    "WHERE migration_name = %s",
                    (migration.name,),
                ).fetchone()
                if row is not None:
                    if row[0] != checksum:
                        raise RuntimeError(
                            f"applied migration changed: {migration.name}; reconcile before deploy"
                        )
                    continue

                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO public.reclaim_schema_migrations (migration_name, checksum)
                    VALUES (%s, %s)
                    """,
                    (migration.name, checksum),
                )
                connection.commit()
                applied += 1
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
            connection.commit()
    return applied


def main() -> None:
    applied = apply_migrations()
    print(f"RECLAIM migrations applied: {applied}")


if __name__ == "__main__":  # pragma: no cover - command-line entry point
    main()


__all__ = ["MIGRATION_DIRECTORY", "apply_migrations", "main", "migration_files"]
