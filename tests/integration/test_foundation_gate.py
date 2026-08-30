"""Foundational architecture gate for T024-T035.

The gate checks every boundary without treating a projection, cache, telemetry
sink, workflow history, or broker watermark as authoritative business state.
Live service checks are enabled by the corresponding environment variables.
"""

import json
import os
from pathlib import Path

import pytest
from app.observability import CorrelationContext, Telemetry
from app.observability.telemetry import InMemoryTelemetrySink
from app.security.boundaries import AllowedCapability, BoundedToolSet
from workflows.case_workflow import ACTIVITY_NAMES

ROOT = Path(__file__).resolve().parents[2]


def test_foundation_gate_covers_declared_ownership_boundaries() -> None:
    assert ACTIVITY_NAMES["read_authoritative_state"] == "case.read_authoritative_state"
    assert (ROOT / "infra/redpanda/topics.yaml").exists()
    assert (ROOT / "infra/keycloak/realm-reclaim.json").exists()
    assert (ROOT / "infra/vault/policies/action-gateway.hcl").exists()
    assert (ROOT / "infra/observability/otel-collector.yaml").exists()
    assert (ROOT / "infra/langfuse/README.md").exists()
    assert (ROOT / "infra/mlflow/README.md").exists()

    realm = json.loads(
        (ROOT / "infra/keycloak/realm-reclaim.json").read_text(encoding="utf-8")
    )
    role_names = {role["name"] for role in realm["roles"]["realm"]}
    assert {"reviewer", "approver", "escalation-owner", "policy-owner"}.issubset(
        role_names
    )

    tools = BoundedToolSet(
        {AllowedCapability.READ_CASE, AllowedCapability.PROPOSE_ACTION}
    )
    assert "database_write" not in tools.names()
    sink = InMemoryTelemetrySink()
    Telemetry(sink).record(
        kind="foundation_gate",
        context=CorrelationContext("tenant-a", "corr-1", case_id="case-1"),
        data={"authorization": "secret", "event_id": "event-1"},
    )
    assert sink.records[0]["data"]["authorization"] == "[REDACTED]"


@pytest.mark.skipif(
    not os.getenv("RECLAIM_DATABASE_URL"), reason="live PostgreSQL URL not configured"
)
def test_foundation_gate_live_postgres_authority() -> None:
    import psycopg

    with (
        psycopg.connect(os.environ["RECLAIM_DATABASE_URL"]) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT to_regclass('public.outbox_events'), to_regclass('public.inbox_messages')"
        )
        assert cursor.fetchone() == ("outbox_events", "inbox_messages")


@pytest.mark.skipif(
    not os.getenv("RECLAIM_RLS_DATABASE_URL"),
    reason="live non-owner RLS URL not configured",
)
def test_foundation_gate_live_postgres_rls() -> None:
    import psycopg

    with (
        psycopg.connect(os.environ["RECLAIM_RLS_DATABASE_URL"]) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET reclaim.tenant_id = 'tenant-a'")
        cursor.execute(
            "SELECT tenant_id FROM tenants WHERE tenant_id IN ('tenant-a', 'tenant-b') ORDER BY tenant_id"
        )
        assert cursor.fetchall() == [("tenant-a",)]
