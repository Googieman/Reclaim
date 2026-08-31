"""Static guardrails for the D3 authority migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_d3_migration_declares_authoritative_mapping_invariants() -> None:
    migration = (
        ROOT / "backend/db/migrations/005_provider_correlation_authority.sql"
    ).read_text(encoding="utf-8")

    for fragment in (
        "CREATE TABLE IF NOT EXISTS provider_correlation_mappings",
        "correlation_schema_version TEXT NOT NULL DEFAULT '1.0.0'",
        "FOREIGN KEY (tenant_id, connector_id)",
        "FOREIGN KEY (tenant_id, incident_id)",
        "FOREIGN KEY (tenant_id, case_id, incident_id)",
        "CHECK (\n        provider_event_id IS NOT NULL",
        "provider_mapping_active_event_idx",
        "provider_mapping_active_payment_idx",
        "provider_mapping_active_order_idx",
        "provider_mapping_active_reference_idx",
        "webhook_delivery_mapping_fkey",
        "webhook_delivery_authority_check",
        "ALTER TABLE provider_correlation_mappings FORCE ROW LEVEL SECURITY",
        "WITH CHECK (tenant_id = reclaim.require_tenant_context())",
    ):
        assert fragment in migration


def test_d3_migration_quarantines_legacy_authority_without_backfill() -> None:
    migration = (
        ROOT / "backend/db/migrations/005_provider_correlation_authority.sql"
    ).read_text(encoding="utf-8")

    assert "INSERT INTO webhook_quarantines" in migration
    assert (
        "unresolved_association: legacy delivery has no verified provider mapping"
        in migration
    )
    assert "DELETE FROM webhook_deliveries" in migration
    assert "delivery.case_id" in migration
    assert "mapping.case_id = delivery.case_id" in migration
