"""Static contracts for the live T153 acceptance boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tests" / "support" / "t153_runtime.py"
ACCEPTANCE = ROOT / "tests" / "acceptance" / "test_t153_n8n_runtime.py"
CONFTST = ROOT / "tests" / "acceptance" / "conftest.py"


def test_t153_acceptance_artifacts_exist_and_are_explicitly_scoped() -> None:
    assert RUNTIME.is_file()
    assert ACCEPTANCE.is_file()

    combined = f"{RUNTIME.read_text(encoding='utf-8')}\n{ACCEPTANCE.read_text(encoding='utf-8')}"
    for name in (
        "RECLAIM_T153_API_BASE_URL",
        "RECLAIM_T153_WEB_BASE_URL",
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
        "RECLAIM_MINIO_ENDPOINT",
        "RECLAIM_T153_PROJECT_NAME",
    ):
        assert name in combined
    assert "tenant-canonical-demo" in combined
    assert "pytest.skip" in combined


def test_t153_acceptance_checks_authoritative_stores_and_tenant_context() -> None:
    combined = f"{RUNTIME.read_text(encoding='utf-8')}\n{ACCEPTANCE.read_text(encoding='utf-8')}"
    for table in (
        "incidents",
        "cases",
        "outbox_events",
        "orchestration_runs",
        "orchestration_stage_attempts",
        "audit_records",
        "timeline_events",
    ):
        assert table in combined
    assert "SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'" in combined
    assert "published_at" in combined
    assert "stage_attempts" in combined
    assert "_assert_snapshot_is_authoritative" in combined
    assert "expected_stage_attempts" in combined
    assert "expected_model_runs" in combined


def test_t153_timeline_snapshot_scopes_rows_by_case_id() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'SELECT count(*) FROM public.timeline_events WHERE {run_scope}' in source
    assert 'SELECT count(*) FROM public.timeline_events WHERE {scope}' not in source
    assert 'SELECT count(*) FROM public.action_executions WHERE {run_scope}' in source
    assert 'SELECT count(*) FROM public.action_executions WHERE {scope}' not in source


def test_t153_acceptance_proves_immutable_checksum_and_exact_broker_duplicate() -> None:
    combined = f"{RUNTIME.read_text(encoding='utf-8')}\n{ACCEPTANCE.read_text(encoding='utf-8')}"
    for marker in (
        "mc cat",
        "mc stat",
        "sha256",
        "AIOKafkaProducer",
        "serialize_event",
        "authoritative",
        "duplicate",
        "execution count",
        "marker-scoped",
        "e.data::text",
    ):
        assert marker.lower() in combined.lower()
    assert "report_content" not in combined
    assert 'b"T153 synthetic operator report" not in serialized' in combined


def test_t153_checksum_validation_keeps_capture_and_narrative_digests_separate() -> None:
    from support import t153_runtime

    raw_checksum = "sha256:" + ("a" * 64)
    narrative_checksum = "sha256:" + ("b" * 64)

    assert raw_checksum != narrative_checksum
    assert t153_runtime.validate_raw_report_checksums(
        {
            "reference_type": "incident.report.raw",
            "checksum": raw_checksum,
        },
        narrative_checksum,
    ) == (raw_checksum, narrative_checksum)


def test_t153_acceptance_conftest_does_not_turn_missing_live_env_into_fake_success() -> None:
    source = CONFTST.read_text(encoding="utf-8")
    assert "InMemoryObjectStorage" not in source
    assert "live MinIO endpoint" in source
    assert "RECLAIM_DATABASE_URL" in source
    assert "def t153_evidence_orchestrator" in source
    assert '"tenant-canonical-demo"' in source


def test_t153_compose_status_parser_accepts_compose_ndjson(monkeypatch) -> None:
    from support import t153_runtime

    monkeypatch.setattr(
        t153_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                '{"Service":"api","State":"running","Health":"healthy"}\n'
                '{"Service":"event-relay","State":"running","Health":""}\n'
            ),
        ),
    )

    config = t153_runtime.T153Config(
        api_base_url="http://127.0.0.1:18000",
        web_base_url="http://127.0.0.1:13000",
        database_url="postgresql://reclaim:test@127.0.0.1:15432/reclaim",
        redpanda_brokers="127.0.0.1:19092",
        minio_endpoint="http://127.0.0.1:19000",
        project_name="reclaim-t153-unit",
    )

    assert t153_runtime.compose_service_statuses(config) == {
        "api": {"state": "running", "health": "healthy"},
        "event-relay": {"state": "running", "health": ""},
    }
