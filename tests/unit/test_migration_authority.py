from __future__ import annotations

from pathlib import Path

from app import migrate as compatibility_migrate
from db import migrate as authoritative_migrate


def test_legacy_migration_module_delegates_to_the_single_authoritative_runner() -> None:
    assert compatibility_migrate.MigrationRunner is authoritative_migrate.MigrationRunner
    assert compatibility_migrate.MigrationError is authoritative_migrate.MigrationError
    assert compatibility_migrate.MIGRATION_DIRECTORY == authoritative_migrate.MIGRATION_DIRECTORY


def test_legacy_migration_file_listing_preserves_authoritative_order() -> None:
    expected = tuple(item.path for item in authoritative_migrate.discover_migrations(
        authoritative_migrate.MIGRATION_DIRECTORY
    ))

    assert compatibility_migrate.migration_files() == expected
    assert all(isinstance(path, Path) for path in compatibility_migrate.migration_files())
