"""Test-first contracts for backup, recovery, and deployment observability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def test_release_preflight_reports_conditional_gate_without_secret_values() -> None:
    from scripts.release_preflight import GateStatus, run_preflight

    report = run_preflight(ROOT)

    assert report.summary == "CONDITIONAL NO-GO"
    assert report.exit_code == 2
    assert report.find("live-qualification").status is GateStatus.OPEN
    assert report.find("temporal-drain").status is GateStatus.OPEN
    assert all("reclaim-n8n-development" not in line for line in report.render())


def test_release_preflight_validates_release_metadata_without_printing_values(
    tmp_path: Path,
) -> None:
    from scripts.release_preflight import GateStatus, run_preflight

    metadata = tmp_path / "release-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "release_id": "reclaim-2026.09.04",
                "source_commit": "a" * 40,
                "api_image_digest": "sha256:" + "b" * 64,
                "web_image_digest": "sha256:" + "c" * 64,
                "provenance": "scripts/build_provenance.py",
            }
        ),
        encoding="utf-8",
    )

    report = run_preflight(ROOT, release_metadata=metadata)

    assert report.find("release-metadata").status is GateStatus.PASS
    rendered = "\n".join(report.render())
    assert "aaaaaaaa" not in rendered
    assert "bbbbbbbb" not in rendered


def test_release_preflight_checks_production_input_names_only(tmp_path: Path) -> None:
    from scripts.release_preflight import GateStatus, run_preflight

    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            [
                "RECLAIM_API_IMAGE=registry.internal/reclaim-api@sha256:" + "a" * 64,
                "RECLAIM_WEB_IMAGE=registry.internal/reclaim-web@sha256:" + "b" * 64,
                "KEYCLOAK_HOSTNAME=identity.internal",
                "RECLAIM_OIDC_AUDIENCE=reclaim-api",
                "RECLAIM_OIDC_JWKS_URL=https://identity.internal/jwks",
                "RECLAIM_VAULT_ADDRESS=https://vault.internal:8200",
                "RECLAIM_REDPANDA_SASL_USERNAME=relay",
                "RECLAIM_REDPANDA_TLS_DIR=C:\\secrets\\redpanda",
                "RECLAIM_SECRET_DIR=C:\\secrets\\runtime",
                "RECLAIM_CONTROL_PLANE_TLS_DIR=C:\\secrets\\control-plane",
                "N8N_HOST=n8n.internal",
                "N8N_DB_PASSWORD=super-secret-value",
                "N8N_ENCRYPTION_KEY=another-secret-value",
                "RECLAIM_N8N_SERVICE_TOKEN=token-value",
                "KEYCLOAK_DB_USERNAME=keycloak",
                "KEYCLOAK_DB_PASSWORD=keycloak-secret",
            ]
        ),
        encoding="utf-8",
    )

    report = run_preflight(ROOT, production_env=env_file)

    assert report.find("production-inputs").status is GateStatus.PASS
    rendered = "\n".join(report.render())
    assert "super-secret-value" not in rendered
    assert "another-secret-value" not in rendered
    assert "token-value" not in rendered


def test_release_preflight_blocks_tampered_release_metadata(tmp_path: Path) -> None:
    from scripts.release_preflight import GateStatus, run_preflight

    metadata = tmp_path / "release-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "release_id": "reclaim-2026.09.04",
                "source_commit": "not-a-sha",
                "api_image_digest": "latest",
                "web_image_digest": "sha256:" + "c" * 64,
                "provenance": "scripts/build_provenance.py",
            }
        ),
        encoding="utf-8",
    )

    report = run_preflight(ROOT, release_metadata=metadata)

    assert report.find("release-metadata").status is GateStatus.BLOCK
    assert report.summary == "NO-GO"


def test_release_preflight_entrypoint_is_read_only_and_documents_gate_meaning() -> None:
    entrypoint = (ROOT / "scripts" / "release-preflight.ps1").read_text(
        encoding="utf-8"
    )
    runbook = (
        (ROOT / "docs" / "operator" / "release-readiness.md")
        .read_text(encoding="utf-8")
        .lower()
    )

    assert "release_preflight.py" in entrypoint
    assert "docker compose" not in entrypoint.lower()
    assert "exit $lastexitcode" in entrypoint.lower()
    for phrase in (
        "conditional no-go",
        "secret values",
        "t153",
        "t154",
        "sbom",
        "rollback",
    ):
        assert phrase in runbook


def test_production_profile_selects_immutable_application_images() -> None:
    production = (INFRA / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "RECLAIM_API_IMAGE:?" in production
    assert "RECLAIM_WEB_IMAGE:?" in production
    assert "RECLAIM_API_IMAGE" in production.split("event-relay:", 1)[1]


def test_backup_policy_declares_authority_integrity_and_recovery_objectives() -> None:
    policy = yaml.safe_load(
        (INFRA / "backup" / "policy.yml").read_text(encoding="utf-8")
    )

    assert policy["authority"] == "postgresql"
    assert policy["rpo_minutes"] == 15
    assert policy["rto_minutes"] == 60
    assert policy["postgresql"]["format"] == "custom"
    assert policy["postgresql"]["integrity"] == "sha256-manifest-and-pg_restore-check"
    assert policy["minio"]["immutable_source_required"] is True
    assert policy["minio"]["integrity"] == "sha256-manifest-and-object-checksum"
    assert policy["restore"]["requires_isolated_target"] is True


def test_backup_and_restore_scripts_are_checksum_verified_and_fail_closed() -> None:
    backup = (ROOT / "scripts" / "backup-postgres.ps1").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "restore-postgres.ps1").read_text(encoding="utf-8")
    minio_backup = (ROOT / "scripts" / "backup-minio.ps1").read_text(encoding="utf-8")
    minio_restore = (ROOT / "scripts" / "restore-minio.ps1").read_text(encoding="utf-8")

    for script in (backup, restore, minio_backup, minio_restore):
        assert "Get-FileHash" in script
        assert "SHA256" in script
        assert "RECLAIM" in script
    assert "pg_dump" in backup and "manifest" in backup
    assert "pg_restore" in restore and "checksum" in restore.lower()
    assert "mc mirror" in minio_backup and "--preserve" in minio_backup
    assert "mc mirror" in minio_restore and "-Confirm" in minio_restore
    assert "object_key_sha256" in minio_restore
    assert "content_sha256" in minio_restore
    assert "aggregate_sha256" in minio_restore
    assert "--overwrite" not in minio_restore


def test_migration_rehearsal_has_rollback_and_authority_guards() -> None:
    runbook = (
        (ROOT / "docs" / "operator" / "migration-rehearsal.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "rollback" in runbook
    assert "pg_restore" in runbook
    assert "isolated" in runbook
    assert "postgresql" in runbook
    assert "n8n" in runbook
    assert "temporal" in runbook
    assert "do not" in runbook


def test_recovery_check_is_scoped_to_non_destructive_service_restart() -> None:
    script = (ROOT / "scripts" / "recovery-check.ps1").read_text(encoding="utf-8")
    assert "docker compose" in script
    assert "restart" in script
    assert "--volumes" not in script
    assert " down " not in script.lower()
    assert "T153" in script
    assert "live" in script.lower()


def test_observability_alerts_cover_durability_integrity_and_recovery() -> None:
    alerts = yaml.safe_load(
        (INFRA / "observability" / "alerts.yml").read_text(encoding="utf-8")
    )
    rules = [rule for group in alerts["groups"] for rule in group["rules"]]
    names = {rule["alert"] for rule in rules}
    assert {
        "ReclaimBackupStale",
        "ReclaimBackupIntegrityFailure",
        "ReclaimPostgresUnavailable",
        "ReclaimOrchestrationStalled",
        "ReclaimRecoveryEscalation",
    } <= names
    for rule in rules:
        assert "runbook_url" in rule["annotations"]
        assert "summary" in rule["annotations"]
        assert "for" in rule


def test_observability_dashboard_is_provisionable_and_uses_redacted_metrics() -> None:
    dashboard = json.loads(
        (
            INFRA / "observability" / "grafana" / "dashboards" / "operations.json"
        ).read_text(encoding="utf-8")
    )
    serialized = json.dumps(dashboard)
    assert dashboard["title"] == "RECLAIM Operations"
    for metric in (
        "reclaim_backup_verification_total",
        "reclaim_orchestration_stage_duration_seconds",
        "reclaim_recovery_events_total",
    ):
        assert metric in serialized
    assert "raw_payload" not in serialized
    assert "authorization" not in serialized


def test_metric_registry_emits_bounded_labels_and_correlation_fields() -> None:
    from app.observability.metrics import MetricRegistry

    registry = MetricRegistry()
    registry.inc(
        "backup_verification",
        labels={"status": "verified", "tenant_id": "tenant-secret-like"},
        context={"correlation_id": "corr-1", "case_id": "case-1"},
    )
    registry.observe(
        "orchestration_stage_duration_seconds",
        0.25,
        labels={"stage": "normalize"},
        context={"correlation_id": "corr-1", "case_id": "case-1"},
    )

    records = registry.records()
    assert records[0]["metric"] == "reclaim_backup_verification_total"
    assert records[0]["labels"] == {"status": "verified"}
    assert records[0]["correlation"] == {
        "correlation_id": "corr-1",
        "case_id": "case-1",
    }
    assert records[1]["value"] == pytest.approx(0.25)
    assert all("tenant-secret-like" not in json.dumps(record) for record in records)


def test_metrics_and_logs_retain_trace_correlation_but_never_untrusted_content() -> (
    None
):
    telemetry = (
        (INFRA / "observability" / "otel-collector.yaml")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "reclaim.correlation_id" in telemetry
    assert "reclaim.case_id" in telemetry
    assert "reclaim.raw_payload" in telemetry
    assert "action: delete" in telemetry


def test_deployment_runbook_is_actionable_and_states_static_vs_live_qualification() -> (
    None
):
    runbook = (
        (ROOT / "docs" / "operator" / "backup-restore.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "rpo" in runbook and "15" in runbook
    assert "rto" in runbook and "60" in runbook
    assert "static readiness" in runbook
    assert "live qualification" in runbook
    assert "minio" in runbook and "postgresql" in runbook
    assert "checksum" in runbook


def test_runtime_settings_have_explicit_bounded_recovery_objectives() -> None:
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        rpo_minutes=15,
        rto_minutes=60,
        backup_retention_days=35,
    )
    assert settings.rpo_minutes == 15
    assert settings.rto_minutes == 60
    assert settings.backup_retention_days == 35
    with pytest.raises(ValueError):
        Settings(_env_file=None, rpo_minutes=0)


def test_api_metrics_endpoint_exposes_operational_metrics_without_sensitive_labels() -> (
    None
):
    from fastapi.testclient import TestClient

    from api.main import create_app
    from app.config import Settings

    application = create_app(
        settings=Settings(
            _env_file=None,
            demo_read_only_enabled=True,
            run_mode="replay",
            replay_label="replay",
            live_actions_enabled=False,
            live_financial_actions_enabled=False,
        )
    )
    response = TestClient(application).get("/metrics")
    assert response.status_code == 200
    assert "reclaim_postgres_health" in response.text
    assert "tenant_id" not in response.text
    assert "authorization" not in response.text
