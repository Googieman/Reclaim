"""Environment-gated helpers for the real T153 acceptance matrix.

This module deliberately has no fallback business store.  Outside the explicit
T153 harness it skips; inside it reads authoritative state from PostgreSQL and
uses only the configured loopback endpoints.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

TENANT_ID = "tenant-canonical-demo"
WORKFLOW_VERSION = "incident-analysis-handoff.v1"
DOMAIN_TOPIC = "reclaim.domain.v1"
TERMINAL_ORCHESTRATION_STATES = frozenset({"awaiting_human", "requires_attention"})
ALLOWLISTED_FAILURE_CODES = frozenset(
    {
        "empty_timeline",
        "model_unavailable",
        "normalize_failed",
        "policy_failed",
        "timeout",
        "upstream_unavailable",
        "unknown_result",
    }
)
REQUIRED_T153_ENVIRONMENT = (
    "RECLAIM_T153_API_BASE_URL",
    "RECLAIM_T153_WEB_BASE_URL",
    "RECLAIM_DATABASE_URL",
    "RECLAIM_REDPANDA_BROKERS",
    "RECLAIM_MINIO_ENDPOINT",
    "RECLAIM_T153_PROJECT_NAME",
)
SAFE_PROJECT = re.compile(r"^reclaim-t153-[a-z0-9-]+$")
REJECTED_PROJECT_EXAMPLE = "reclaim-demo"
RECOVERY_SERVICES = frozenset({"n8n-worker", "api", "redis"})
RECOVERY_ACTIONS = frozenset({"start", "stop", "restart"})


@dataclass(frozen=True, slots=True)
class T153Config:
    api_base_url: str
    web_base_url: str
    database_url: str
    redpanda_brokers: str
    minio_endpoint: str
    project_name: str

    @classmethod
    def from_environment(cls) -> T153Config | None:
        values = {name: os.getenv(name, "").strip() for name in REQUIRED_T153_ENVIRONMENT}
        if any(not value for value in values.values()):
            return None
        if not SAFE_PROJECT.fullmatch(values["RECLAIM_T153_PROJECT_NAME"]):
            raise ValueError("RECLAIM_T153_PROJECT_NAME is not a safe T153 project")
        return cls(
            api_base_url=values["RECLAIM_T153_API_BASE_URL"].rstrip("/"),
            web_base_url=values["RECLAIM_T153_WEB_BASE_URL"].rstrip("/"),
            database_url=values["RECLAIM_DATABASE_URL"],
            redpanda_brokers=values["RECLAIM_REDPANDA_BROKERS"],
            minio_endpoint=values["RECLAIM_MINIO_ENDPOINT"],
            project_name=values["RECLAIM_T153_PROJECT_NAME"],
        )


def require_t153_config() -> T153Config:
    config = T153Config.from_environment()
    if config is None:
        import pytest

        pytest.skip(
            "T153 acceptance requires the explicit prepared-stack environment: "
            + ", ".join(REQUIRED_T153_ENVIRONMENT)
        )
    return config


def unique_marker(prefix: str = "t153") -> str:
    """Return an opaque identity used in requests, never a narrative value."""

    normalized = re.sub(r"[^a-z0-9-]+", "-", prefix.lower()).strip("-") or "t153"
    return f"{normalized}-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:12]}"


def reviewer_headers(marker: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer demo-reviewer",
        "X-Correlation-ID": marker,
    }


def intake_payload(marker: str) -> dict[str, Any]:
    occurred_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "tenant_id": TENANT_ID,
        "correlation_id": marker,
        "source": "merchant_portal",
        "received_at": occurred_at,
        "incident_type": "unauthorized_payment",
        "occurred_at": occurred_at,
        "narrative": "T153 synthetic operator report; validation data only.",
        "payment_reference": marker,
        "reported_amount_minor": 12345,
        "reported_currency": "INR",
        "external_reference": marker,
        "reporter_context": {"validation": "t153"},
        "idempotency_key": marker,
    }


def post_intake(
    config: T153Config, marker: str, *, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    import httpx

    response = httpx.post(
        f"{config.api_base_url}/tenants/{TENANT_ID}/incidents",
        headers=reviewer_headers(marker),
        json=intake_payload(marker) if payload is None else payload,
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def readiness(config: T153Config) -> dict[str, Any]:
    import httpx

    response = httpx.get(f"{config.api_base_url}/health/ready", timeout=10.0)
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "ready"
    assert body["mode"] == "live"
    assert body["live_actions_enabled"] is False
    assert body["live_financial_actions_enabled"] is False
    return body


def web_cases_response(config: T153Config, marker: str) -> dict[str, Any]:
    import httpx

    response = httpx.get(
        f"{config.web_base_url}/cases",
        headers={"Accept": "text/html"},
        timeout=15.0,
    )
    response.raise_for_status()
    assert response.status_code == 200
    return {"status_code": response.status_code, "body_sha256": hashlib.sha256(response.content).hexdigest()}


def compose_service_statuses(config: T153Config) -> dict[str, dict[str, str]]:
    """Read only the service/status fields needed for the T153 health proof."""

    compose_files = [
        str(Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml"),
        str(Path(__file__).resolve().parents[2] / "infra" / "docker-compose.t153.yml"),
    ]
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            config.project_name,
            "-f",
            compose_files[0],
            "-f",
            compose_files[1],
            "--profile",
            "t153",
            "ps",
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError("T153 Compose health query failed")
    rows = _parse_compose_status_rows(result.stdout)
    return {
        str(row["Service"]): {
            "state": str(row.get("State", "")),
            "health": str(row.get("Health", "")),
        }
        for row in rows
    }


def _parse_compose_status_rows(output: str) -> list[dict[str, Any]]:
    """Accept Compose's array and newline-delimited JSON output variants."""

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        try:
            parsed = [json.loads(line) for line in output.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise AssertionError("T153 Compose health query was not JSON") from exc
    rows = parsed if isinstance(parsed, list) else [parsed]
    if not all(isinstance(row, dict) for row in rows):
        raise AssertionError("T153 Compose health query returned invalid rows")
    return rows


def compose_service_command(
    config: T153Config, service: str, action: str = "restart"
) -> list[str]:
    """Build a bounded recovery command for one T153 service only."""

    if not SAFE_PROJECT.fullmatch(config.project_name):
        raise ValueError("T153 recovery requires a uniquely prefixed project")
    if service not in RECOVERY_SERVICES:
        raise ValueError("T153 recovery service is not allowlisted")
    if action not in RECOVERY_ACTIONS:
        raise ValueError("T153 recovery action is not allowlisted")

    root = Path(__file__).resolve().parents[2]
    return [
        "docker",
        "compose",
        "-p",
        config.project_name,
        "-f",
        str(root / "infra" / "docker-compose.yml"),
        "-f",
        str(root / "infra" / "docker-compose.t153.yml"),
        "--profile",
        "t153",
        action,
        service,
    ]


def restart_t153_service(
    config: T153Config, service: str, action: str = "restart"
) -> float:
    """Run one allowlisted service action and return elapsed seconds."""

    started = time.monotonic()
    result = subprocess.run(
        compose_service_command(config, service, action),
        capture_output=True,
        check=False,
        text=True,
    )
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        raise AssertionError("T153 recovery service action failed")
    return elapsed


def redis_queue_state(config: T153Config) -> dict[str, Any]:
    """Read queue depth and AOF health without reading any Redis job body."""

    root = Path(__file__).resolve().parents[2]
    compose = [
        "docker",
        "compose",
        "-p",
        config.project_name,
        "-f",
        str(root / "infra" / "docker-compose.yml"),
        "-f",
        str(root / "infra" / "docker-compose.t153.yml"),
        "--profile",
        "t153",
        "exec",
        "-T",
        "redis",
        "sh",
        "-c",
    ]
    script = """
set -eu
ping=$(redis-cli -n 2 ping)
key_count=0
queue_depth=0
for key in $(redis-cli -n 2 --scan --pattern 'bull:*'); do
  key_count=$((key_count + 1))
  case "$key" in
    *:wait|*:active|*:delayed|*:prioritized|*:paused|*:waiting-children)
      case "$(redis-cli -n 2 TYPE "$key")" in
        list) queue_depth=$((queue_depth + $(redis-cli -n 2 LLEN "$key"))) ;;
        zset) queue_depth=$((queue_depth + $(redis-cli -n 2 ZCARD "$key"))) ;;
        set) queue_depth=$((queue_depth + $(redis-cli -n 2 SCARD "$key"))) ;;
        stream) queue_depth=$((queue_depth + $(redis-cli -n 2 XLEN "$key"))) ;;
      esac
  esac
done
aof_enabled=$(redis-cli -n 2 INFO persistence | awk -F: '/^aof_enabled:/{print $2}' | tr -d '\r')
aof_last_load_status=$(redis-cli -n 2 INFO persistence | awk -F: '/^aof_last_load_status:/{print $2}' | tr -d '\r')
printf 'ping=%s\nkey_count=%s\nqueue_depth=%s\naof_enabled=%s\naof_last_load_status=%s\n' "$ping" "$key_count" "$queue_depth" "$aof_enabled" "${aof_last_load_status:-missing}"
"""
    result = subprocess.run(
        compose + [script], capture_output=True, check=False, text=True
    )
    if result.returncode != 0:
        raise AssertionError("T153 Redis queue health query failed")
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if values.get("ping") != "PONG":
        raise AssertionError("T153 Redis health query did not return PONG")
    return {
        "key_count": int(values.get("key_count", "0")),
        "queue_depth": int(values.get("queue_depth", "0")),
        "aof_enabled": values.get("aof_enabled") == "1",
        "aof_last_load_status": values.get("aof_last_load_status", "missing"),
    }


def n8n_execution_count(config: T153Config, marker: str) -> int | None:
    """Read marker-scoped n8n executions without requiring its API key."""

    root = Path(__file__).resolve().parents[2]
    sql = """
        SELECT count(*)
        FROM n8n.execution_entity e
        JOIN n8n.workflow_entity w ON w.id = e."workflowId"
        WHERE w.name = 'incident-analysis-handoff.v1'
          AND COALESCE(e.data::text, '') LIKE '%' || :'marker' || '%'
    """
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            config.project_name,
            "-f",
            str(root / "infra" / "docker-compose.yml"),
            "-f",
            str(root / "infra" / "docker-compose.t153.yml"),
            "--profile",
            "t153",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "reclaim",
            "-d",
            "reclaim",
            "-At",
            "-v",
            f"marker={marker}",
            "-c",
            sql,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def assert_schema_contract(config: T153Config) -> None:
    """Prove the fresh database has the tenant/RLS/n8n objects required by T153."""

    import psycopg

    required_tables = {
        "incidents",
        "cases",
        "outbox_events",
        "orchestration_runs",
        "orchestration_stage_attempts",
        "audit_records",
        "timeline_events",
    }
    with psycopg.connect(config.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'")
            cursor.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = ANY(%s)
                """,
                (list(required_tables),),
            )
            rows = {str(row[0]): (bool(row[1]), bool(row[2])) for row in cursor.fetchall()}
            assert set(rows) == required_tables
            assert all(enabled and forced for enabled, forced in rows.values())
            cursor.execute(
                "SELECT schema_owner FROM information_schema.schemata WHERE schema_name = 'n8n'"
            )
            owner = cursor.fetchone()
            assert owner is not None and owner[0] == "n8n"


def raw_report_reference(config: T153Config, marker: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(config.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'")
            cursor.execute(
                """
                SELECT raw_input_reference, narrative_checksum
                FROM public.incidents
                WHERE tenant_id = 'tenant-canonical-demo'
                  AND (deduplication_identity = %s OR correlation_key = %s)
                """,
                (marker, marker),
            )
            row = cursor.fetchone()
    if row is None or not row[0]:
        raise AssertionError("T153 immutable raw report reference is missing")
    reference = json.loads(str(row[0]))
    _, narrative_checksum = validate_raw_report_checksums(reference, row[1])
    return {**reference, "narrative_checksum": narrative_checksum}


def validate_raw_report_checksums(
    reference: dict[str, Any], narrative_checksum: object
) -> tuple[str, str]:
    """Validate the raw-capture and narrative checksums as separate digests."""

    if reference.get("reference_type") != "incident.report.raw":
        raise AssertionError("T153 raw report reference has an unexpected type")
    raw_checksum = reference.get("checksum")
    if not isinstance(raw_checksum, str) or not _is_sha256_checksum(raw_checksum):
        raise AssertionError("T153 raw report checksum is missing or malformed")
    if not isinstance(narrative_checksum, str) or not _is_sha256_checksum(narrative_checksum):
        raise AssertionError("T153 narrative checksum is missing or malformed")
    return raw_checksum, narrative_checksum


def _is_sha256_checksum(value: str) -> bool:
    return bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def verify_minio_raw_report(config: T153Config, marker: str) -> dict[str, Any]:
    """Download/hash the one raw object in-container without exposing its bytes."""

    from urllib.parse import urlparse

    reference = raw_report_reference(config, marker)
    parsed = urlparse(str(reference["reference_id"]))
    bucket, separator, object_name = parsed.path.lstrip("/").partition("/")
    if parsed.scheme != "minio" or not bucket or not separator or not object_name:
        raise AssertionError("T153 raw report reference is not a valid MinIO URI")
    root = Path(__file__).resolve().parents[2]
    compose = [
        "docker",
        "compose",
        "-p",
        config.project_name,
        "-f",
        str(root / "infra" / "docker-compose.yml"),
        "-f",
        str(root / "infra" / "docker-compose.t153.yml"),
        "--profile",
        "t153",
        "exec",
        "-T",
        "minio",
    ]
    command = (
        "mc alias set local http://127.0.0.1:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" "
        ">/dev/null 2>&1 && mc stat --json local/"
        + bucket
        + "/"
        + object_name
    )
    stat = subprocess.run(compose + ["sh", "-c", command], capture_output=True, check=False)
    if stat.returncode != 0:
        raise AssertionError("T153 MinIO metadata query failed")
    try:
        metadata = json.loads(stat.stdout.decode("utf-8").splitlines()[-1])
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError("T153 MinIO metadata was not JSON") from exc
    content = subprocess.run(
        compose
        + [
            "sh",
            "-c",
            "mc alias set local http://127.0.0.1:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" "
            ">/dev/null 2>&1 && mc cat local/" + bucket + "/" + object_name,
        ],
        capture_output=True,
        check=False,
    )
    if content.returncode != 0:
        raise AssertionError("T153 MinIO raw object download failed")
    checksum = f"sha256:{hashlib.sha256(content.stdout).hexdigest()}"
    expected_metadata = metadata.get("metadata", {})
    expected = expected_metadata.get("X-Amz-Meta-Sha256") or expected_metadata.get("x-amz-meta-sha256")
    assert expected in {checksum, checksum.removeprefix("sha256:")}
    assert str(reference["checksum"]) == checksum
    return {"bucket": bucket, "object_name": object_name, "checksum": checksum, "size": len(content.stdout)}


def list_cases(config: T153Config, marker: str) -> list[dict[str, Any]]:
    import httpx

    response = httpx.get(
        f"{config.api_base_url}/tenants/{TENANT_ID}/cases",
        params={"q": marker, "limit": 100},
        headers=reviewer_headers(marker),
        timeout=15.0,
    )
    response.raise_for_status()
    return list(response.json().get("items", []))


def wait_for_terminal_case(
    config: T153Config,
    marker: str,
    *,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_item: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        items = [item for item in list_cases(config, marker) if item.get("external_reference") == marker]
        if len(items) > 1:
            raise AssertionError("marker matched more than one authoritative case")
        if items:
            last_item = items[0]
            orchestration = last_item.get("orchestration") or {}
            status = orchestration.get("status")
            if status in TERMINAL_ORCHESTRATION_STATES:
                failure_code = orchestration.get("failure_code")
                if status == "requires_attention":
                    assert failure_code in ALLOWLISTED_FAILURE_CODES
                return last_item
        time.sleep(poll_seconds)
    status = None if last_item is None else (last_item.get("orchestration") or {}).get("status")
    raise AssertionError(f"T153 case did not reach an allowed terminal state; status={status!r}")


def wait_for_condition(
    predicate: Callable[[], Any], *, timeout_seconds: float = 90.0, poll_seconds: float = 1.0
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(poll_seconds)
    raise AssertionError("T153 condition timed out")


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    incidents: int
    cases: int
    accepted_outbox: int
    published_outbox: int
    orchestration_runs: int
    stage_attempts: int
    duplicate_stage_keys: int
    intake_audits: int
    timeline_events: int
    model_runs: int
    action_executions: int


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    scenario: str
    before: DurableSnapshot
    after: DurableSnapshot
    elapsed_seconds: float
    metadata: dict[str, Any]


def record_recovery_observation(
    config: T153Config,
    *,
    scenario: str,
    before: DurableSnapshot,
    after: DurableSnapshot,
    elapsed_seconds: float,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist sanitized restart evidence without markers, payloads, or secrets."""

    if not SAFE_PROJECT.fullmatch(config.project_name):
        raise ValueError("T153 recovery requires a uniquely prefixed project")
    normalized = re.sub(r"[^a-z0-9-]+", "-", scenario.lower()).strip("-") or "recovery"
    observation = RecoveryObservation(
        scenario=normalized,
        before=before,
        after=after,
        elapsed_seconds=round(float(elapsed_seconds), 3),
        metadata=dict(metadata or {}),
    )
    destination = (
        Path(__file__).resolve().parents[2]
        / "tmp"
        / "t153"
        / config.project_name
        / "recovery"
    )
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{normalized}-{uuid.uuid4().hex[:12]}.json"
    output.write_text(
        json.dumps(
            {
                "scenario": observation.scenario,
                "before": asdict(observation.before),
                "after": asdict(observation.after),
                "elapsed_seconds": observation.elapsed_seconds,
                "metadata": observation.metadata,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return output


@dataclass(frozen=True, slots=True)
class AuthoritativeOutboxEvent:
    outbox_id: str
    event: Any
    published_at: datetime | None
    serialized: bytes


def _count(cursor: Any, query: str, params: tuple[Any, ...]) -> int:
    cursor.execute(query, params)
    return int(cursor.fetchone()[0])


def postgres_snapshot(config: T153Config, marker: str) -> DurableSnapshot:
    import psycopg

    with psycopg.connect(config.database_url) as connection:
        with connection.cursor() as cursor:
            # Keep this literal tenant setting visible in the acceptance contract.
            cursor.execute("SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'")
            scope = """
                tenant_id = 'tenant-canonical-demo'
                AND incident_id IN (
                    SELECT incident_id FROM public.incidents
                    WHERE tenant_id = 'tenant-canonical-demo'
                      AND (deduplication_identity = %s OR correlation_key = %s)
                )
            """
            incident_filter = "tenant_id = 'tenant-canonical-demo' AND (deduplication_identity = %s OR correlation_key = %s)"
            incidents = _count(
                cursor,
                f"SELECT count(*) FROM public.incidents WHERE {incident_filter}",
                (marker, marker),
            )
            cases = _count(cursor, f"SELECT count(*) FROM public.cases WHERE {scope}", (marker, marker))
            accepted_outbox = _count(
                cursor,
                """
                SELECT count(*) FROM public.outbox_events
                WHERE tenant_id = 'tenant-canonical-demo'
                  AND event_type = 'incident.accepted' AND correlation_id = %s
                """,
                (marker,),
            )
            published_outbox = _count(
                cursor,
                """
                SELECT count(*) FROM public.outbox_events
                WHERE tenant_id = 'tenant-canonical-demo'
                  AND event_type = 'incident.accepted' AND correlation_id = %s
                  AND published_at IS NOT NULL
                """,
                (marker,),
            )
            run_scope = """
                tenant_id = 'tenant-canonical-demo' AND case_id IN (
                    SELECT c.case_id FROM public.cases c
                    WHERE c.tenant_id = 'tenant-canonical-demo'
                      AND c.incident_id IN (
                        SELECT i.incident_id FROM public.incidents i
                        WHERE i.tenant_id = 'tenant-canonical-demo'
                          AND (i.deduplication_identity = %s OR i.correlation_key = %s)
                      )
                )
            """
            orchestration_runs = _count(
                cursor, f"SELECT count(*) FROM public.orchestration_runs WHERE {run_scope}", (marker, marker)
            )
            stage_attempts = _count(
                cursor,
                f"""SELECT count(*) FROM public.orchestration_stage_attempts
                    WHERE tenant_id = 'tenant-canonical-demo' AND run_id IN
                    (SELECT run_id FROM public.orchestration_runs WHERE {run_scope})""",
                (marker, marker),
            )
            duplicate_stage_keys = _count(
                cursor,
                f"""SELECT count(*) FROM (
                    SELECT run_id, stage, idempotency_key
                    FROM public.orchestration_stage_attempts
                    WHERE tenant_id = 'tenant-canonical-demo' AND run_id IN
                    (SELECT run_id FROM public.orchestration_runs WHERE {run_scope})
                    GROUP BY run_id, stage, idempotency_key
                    HAVING count(*) > 1
                ) AS duplicate_stage_keys""",
                (marker, marker),
            )
            intake_audits = _count(
                cursor,
                """
                SELECT count(*) FROM public.audit_records
                WHERE tenant_id = 'tenant-canonical-demo' AND action = 'incident.intake'
                  AND %s = ANY(correlation_ids)
                """,
                (marker,),
            )
            timeline_events = _count(
                cursor,
                f"SELECT count(*) FROM public.timeline_events WHERE {run_scope}",
                (marker, marker),
            )
            model_runs = _count(cursor, f"SELECT count(*) FROM public.model_runs WHERE {run_scope}", (marker, marker))
            action_executions = _count(
                cursor, f"SELECT count(*) FROM public.action_executions WHERE {run_scope}", (marker, marker)
            )
    return DurableSnapshot(
        incidents=incidents,
        cases=cases,
        accepted_outbox=accepted_outbox,
        published_outbox=published_outbox,
        orchestration_runs=orchestration_runs,
        stage_attempts=stage_attempts,
        duplicate_stage_keys=duplicate_stage_keys,
        intake_audits=intake_audits,
        timeline_events=timeline_events,
        model_runs=model_runs,
        action_executions=action_executions,
    )


def authoritative_outbox_event(config: T153Config, marker: str) -> AuthoritativeOutboxEvent:
    import psycopg

    from packages.contracts.events import EventEnvelope
    from app.events.redpanda import serialize_event

    with psycopg.connect(config.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'")
            cursor.execute(
                """
                SELECT outbox_id, event_id, event_type, aggregate_type, aggregate_id,
                       occurred_at, produced_at, correlation_id, causation_id, producer,
                       payload_checksum, payload, published_at, schema_version
                FROM public.outbox_events
                WHERE tenant_id = 'tenant-canonical-demo'
                  AND event_type = 'incident.accepted' AND correlation_id = %s
                ORDER BY created_at, outbox_id
                """,
                (marker,),
            )
            row = cursor.fetchone()
    if row is None:
        raise AssertionError("authoritative incident.accepted outbox row is missing")
    event = EventEnvelope(
        tenant_id=TENANT_ID,
        correlation_id=str(row[7]),
        event_id=str(row[1]),
        event_type=str(row[2]),
        aggregate_type=str(row[3]),
        aggregate_id=str(row[4]),
        occurred_at=row[5],
        produced_at=row[6],
        causation_id=str(row[8]),
        producer=str(row[9]),
        schema_version=str(row[13]),
        payload_checksum=str(row[10]),
        payload=dict(row[11]),
    )
    serialized = serialize_event(event)
    assert hashlib.sha256(serialized).hexdigest()  # record no content in logs
    assert b"T153 synthetic operator report" not in serialized
    return AuthoritativeOutboxEvent(
        outbox_id=str(row[0]),
        event=event,
        published_at=row[12],
        serialized=serialized,
    )


async def republish_authoritative_event(
    config: T153Config, marker: str
) -> AuthoritativeOutboxEvent:
    from aiokafka import AIOKafkaProducer
    from app.events.redpanda import event_headers

    authoritative = authoritative_outbox_event(config, marker)
    producer = AIOKafkaProducer(bootstrap_servers=config.redpanda_brokers)
    await producer.start()
    try:
        await producer.send_and_wait(
            DOMAIN_TOPIC,
            key=authoritative.event.aggregate_id.encode("utf-8"),
            value=authoritative.serialized,
            headers=event_headers(authoritative.event),
        )
    finally:
        await producer.stop()
    return authoritative


def require_n8n_execution_observation() -> None:
    """Fail closed when operational n8n execution evidence is unavailable."""

    raise AssertionError(
        "T153 evidence limitation: no n8n execution-count observation was provided "
        "by the prepared harness; broker duplicate handling cannot pass by inference."
    )


async def wait_for_async_condition(
    predicate: Callable[[], Any], *, timeout_seconds: float = 60.0, interval_seconds: float = 1.0
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        await asyncio.sleep(interval_seconds)
    raise AssertionError("T153 asynchronous condition timed out")
