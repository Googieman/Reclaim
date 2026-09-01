"""Static safety checks for the MAJOR-2 canonical-action migration."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "db" / "migrations" / "010_canonical_action_identity.sql"


def test_migration_010_uses_one_rls_scoped_canonical_identity_authority() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "CREATE TABLE IF NOT EXISTS public.canonical_actions",
        "PRIMARY KEY (tenant_id, canonical_action_id)",
        "ADD COLUMN canonical_action_id TEXT",
        "model_run_proposals_canonical_action_fkey",
        "REFERENCES public.canonical_actions",
        "model_run_proposals_canonical_action_idx",
        "ALTER TABLE public.canonical_actions FORCE ROW LEVEL SECURITY",
        "ON public.canonical_actions\n    USING (tenant_id = reclaim.require_tenant_context())",
        "REVOKE ALL ON TABLE public.canonical_actions FROM PUBLIC",
        "GRANT SELECT, INSERT ON TABLE public.canonical_actions TO reclaim_app",
        "cannot safely backfill historical model_run_proposals canonical identities",
    ):
        assert fragment in migration


def test_migration_010_does_not_rewrite_prior_migrations_or_grant_mutation() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "007_model_analysis_runs" not in migration
    assert "008_model_analysis_runtime_grants" not in migration
    assert "009_model_analysis_terminal_outcomes" not in migration
    assert "GRANT UPDATE" not in migration
    assert "GRANT DELETE" not in migration
