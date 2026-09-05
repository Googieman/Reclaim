"""Compatibility imports for the single authoritative migration runner.

Deployments must invoke ``python -m db.migrate``. This module remains only for
older launchers that imported ``app.migrate``; it delegates all discovery,
checksumming, locking, and application semantics to ``db.migrate``.
"""

from __future__ import annotations

import os
from pathlib import Path

from db.migrate import (
    LEDGER_TABLE,
    MIGRATION_DIRECTORY,
    MIGRATION_LOCK_KEY,
    Migration,
    MigrationApply,
    MigrationCheck,
    MigrationError,
    MigrationRunner,
    discover_migrations,
    main,
    migration_files,
)


def apply_migrations(
    database_url: str | None = None, *, directory: Path = MIGRATION_DIRECTORY
) -> int:
    """Apply migrations through the canonical runner for legacy callers."""

    resolved_url = database_url or os.environ.get("RECLAIM_MIGRATION_DATABASE_URL")
    resolved_url = resolved_url or os.environ.get("RECLAIM_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError("RECLAIM_MIGRATION_DATABASE_URL or RECLAIM_DATABASE_URL is required")

    import psycopg

    with psycopg.connect(resolved_url) as connection:
        return len(MigrationRunner(connection, migration_dir=directory).apply().applied)


__all__ = [
    "LEDGER_TABLE",
    "MIGRATION_DIRECTORY",
    "MIGRATION_LOCK_KEY",
    "Migration",
    "MigrationApply",
    "MigrationCheck",
    "MigrationError",
    "MigrationRunner",
    "apply_migrations",
    "discover_migrations",
    "main",
    "migration_files",
]
