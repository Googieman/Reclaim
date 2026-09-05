"""Static safety gates for the additive T095-T098 migration."""

from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "backend"
    / "db"
    / "migrations"
    / "012_us3_action_lifecycle.sql"
)


def test_action_lifecycle_migration_is_additive_fail_closed_and_tenant_scoped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists" in sql
    assert "migration 012 cannot safely infer" in sql
    assert "alter table public.action_executions" in sql
    assert "alter table public.action_executions force row level security" in sql
    assert "alter table public.verifications force row level security" in sql
    assert "alter table public.escalations force row level security" in sql
    assert "using (tenant_id = reclaim.require_tenant_context())" in sql
    assert "with check (tenant_id = reclaim.require_tenant_context())" in sql
    assert "unique (tenant_id, canonical_action_id)" in sql
    assert "action_executions_canonical_case_fkey" in sql
    assert "verifications_execution_canonical_case_fkey" in sql
    assert "action_executions_execution_canonical_case_unique" in sql
    assert "verifications_execution_resource_fkey" in sql
    assert "correlation_id" in sql
    assert "revoke all on table" in sql
    assert (
        "grant select, insert, update on table public.action_executions to reclaim_app"
        in sql
    )


def test_action_lifecycle_mutations_are_state_guarded() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    repository = (
        Path(__file__).parents[2]
        / "backend"
        / "app"
        / "db"
        / "repositories"
        / "actions.py"
    ).read_text(encoding="utf-8").lower()
    assert "and status in ('validated', 'pending_remote')" in repository
    assert "and status in ('completed', 'reconciled', 'verifying')" in repository
    assert "and status in (" in repository
    assert all(
        f"'{status}'" in repository
        for status in (
            "completed",
            "failed",
            "reconciled",
            "verifying",
            "unknown",
            "reconciling",
            "escalated",
        )
    )
    assert "where tenant_id = %s and execution_id = %s and status = 'reconciling'" in repository
    assert "action_executions_unknown_reconciliation_check" in sql


def test_action_lifecycle_migration_reasserts_append_only_audit() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "drop trigger if exists audit_records_append_only" in sql
    assert "before update or delete on public.audit_records" in sql
    assert "reclaim_reject_audit_mutation" in sql
