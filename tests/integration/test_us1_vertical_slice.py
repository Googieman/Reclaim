"""T058 complete live US1 intake-to-timeline vertical-slice gate."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
import pytest
from api.workflow_commands import CaseWorkflowCommandService
from app.auth.oidc import (
    AuthenticatedPrincipal,
    IdentityType,
    OIDCVerifier,
    TenantAuthorizationContext,
)
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import IncidentEventConsumer
from app.events.redpanda import EventTransportError, deserialize_event, serialize_event
from app.events.timeline_events import TimelineEventConsumer
from app.intake.service import IncidentIntakeService
from app.intake.webhook_processing import WebhookProcessingService
from app.storage.minio_evidence import ImmutableEvidenceStore, checksum_for_bytes
from connectors.razorpay.manifest import build_razorpay_test_mode_manifest
from connectors.razorpay.webhook import RazorpayWebhookVerifier
from connectors.simulators.evidence import (
    EvidenceSimulatorScenario,
    build_default_evidence_simulators,
)
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage
from projections.neo4j_case_projection import (
    Neo4jCaseProjection,
    Neo4jCaseProjectionConsumer,
)
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner
from timeline.reconstruct import TimelineReconstructor
from workflows.commands import CaseWorkflowCommand
from workflows.worker import CaseWorkerDependencies, create_case_worker

from packages.contracts.connectors import EvidenceRequest
from packages.contracts.events import EventType
from packages.contracts.intake import (
    IncidentIntakeRequest,
    IntakeStatus,
    RazorpayWebhookRequest,
)

ISSUER = "https://identity.example/realms/reclaim"
AUDIENCE = "reclaim-api"
SIGNING_KEY = "t058-test-only-signing-key"
WEBHOOK_SECRET = "t058-test-only-webhook-secret"


def _required_live_environment() -> dict[str, str]:
    names = (
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
        "RECLAIM_NEO4J_URI",
        "RECLAIM_NEO4J_USER",
        "RECLAIM_NEO4J_PASSWORD",
        "RECLAIM_MINIO_ENDPOINT",
        "RECLAIM_MINIO_ACCESS_KEY",
        "RECLAIM_MINIO_SECRET_KEY",
        "RECLAIM_TEMPORAL_TARGET",
    )
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        pytest.skip("T058 live services are not configured: " + ", ".join(missing))
    return {name: os.environ[name] for name in names}


def _principal(
    tenant_id: str,
    *,
    subject: str,
    identity_type: IdentityType,
    roles: frozenset[str],
) -> TenantAuthorizationContext:
    principal = AuthenticatedPrincipal(
        subject=subject,
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: roles},
        identity_type=identity_type,
        issuer=ISSUER,
    )
    return principal.for_tenant(tenant_id)


def _token(tenant_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "t058-reviewer",
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "tenant_ids": [tenant_id],
            "tenant_roles": {tenant_id: ["reviewer"]},
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


def _database_factory(database_url: str):
    import psycopg

    return lambda context: PostgresUnitOfWork(
        lambda: psycopg.connect(database_url),
        authorization_context=context,
    )


def _intake_request(
    tenant_id: str, *, key: str, received_at: datetime
) -> IncidentIntakeRequest:
    return IncidentIntakeRequest(
        tenant_id=tenant_id,
        correlation_id=f"corr-{key}",
        source="operator",
        received_at=received_at,
        reporter_context={"subject": "t058-reviewer", "channel": "live-gate"},
        report_content="Account compromise report; customer instructions remain untrusted evidence.",
        idempotency_key=key,
    )


def _evidence_requests(
    orchestrator: EvidenceOrchestrator,
    *,
    tenant_id: str,
    case_id: str,
    correlation_id: str,
) -> tuple[EvidenceRequest, ...]:
    return orchestrator.requests_for_case(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=correlation_id,
        requested_at=datetime(2026, 8, 30, 10, 1, tzinfo=UTC),
    )


def _webhook_request(
    *,
    tenant_id: str,
    provider_event_id: str,
    signature: str,
    payload: bytes,
    correlation_id: str,
) -> RazorpayWebhookRequest:
    return RazorpayWebhookRequest(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        connector_id="razorpay-test",
        original_payload=payload,
        payload_checksum=checksum_for_bytes(payload),
        signature=signature,
        provider_event_id=provider_event_id,
        event_type="payment.captured",
        event_timestamp=datetime(2026, 8, 30, 9, 45, tzinfo=UTC),
        received_at=datetime(2026, 8, 30, 10, 2, tzinfo=UTC),
    )


async def _consume_events(
    *,
    topic: str,
    expected_event_ids: set[str],
    database_url: str,
    service_context: TenantAuthorizationContext,
    projection_consumer: Neo4jCaseProjectionConsumer,
    projection_events: list[Any],
) -> list[Any]:
    from aiokafka import AIOKafkaConsumer

    group_id = f"t058-gate-{uuid4().hex}"
    broker_consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=os.environ["RECLAIM_REDPANDA_BROKERS"],
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await broker_consumer.start()
    received: list[Any] = []
    factory = _database_factory(database_url)
    incident_consumer = IncidentEventConsumer()
    timeline_consumer = TimelineEventConsumer()
    pending_event_ids = set(expected_event_ids)
    try:
        while pending_event_ids:
            message = await asyncio.wait_for(broker_consumer.getone(), timeout=30)
            event = deserialize_event(message.value)
            if event.event_id not in pending_event_ids:
                continue
            pending_event_ids.remove(event.event_id)
            received.append(event)
            if event.event_type in {
                EventType.INCIDENT_ACCEPTED,
                EventType.WEBHOOK_QUARANTINED,
            }:
                await incident_consumer.dispatch(
                    message.value,
                    unit_of_work_factory=factory,
                    authorization_context=service_context,
                )
            elif event.event_type in {
                EventType.EVIDENCE_COLLECTED,
                EventType.TIMELINE_REBUILT,
            }:
                await timeline_consumer.dispatch(
                    message.value,
                    unit_of_work_factory=factory,
                    authorization_context=service_context,
                )
            if event.event_type in Neo4jCaseProjection.SUPPORTED_EVENT_TYPES:
                projection_events.append(event)
            await projection_consumer.dispatch(
                message.value,
                unit_of_work_factory=factory,
                authorization_context=service_context,
            )
    finally:
        await broker_consumer.stop()
    return received


@pytest.mark.integration
@pytest.mark.asyncio
async def test_us1_live_vertical_slice_gate() -> None:
    """Prove authenticated intake through authoritative timeline and projection replay."""

    settings = _required_live_environment()
    import psycopg
    from fastapi.testclient import TestClient

    tenant_id = f"t058-live-{uuid4().hex[:12]}"
    tenant_b = f"t058-other-{uuid4().hex[:12]}"
    user_context = _principal(
        tenant_id,
        subject="t058-reviewer",
        identity_type=IdentityType.USER,
        roles=frozenset({"reviewer"}),
    )
    service_context = _principal(
        tenant_id,
        subject="reclaim-event-relay",
        identity_type=IdentityType.SERVICE,
        roles=frozenset({"service"}),
    )
    factory = _database_factory(settings["RECLAIM_DATABASE_URL"])

    with PostgresUnitOfWork(
        lambda: psycopg.connect(settings["RECLAIM_DATABASE_URL"]),
        authorization_context=user_context,
    ) as unit_of_work:
        unit_of_work.tenants.create(tenant_id=tenant_id, display_name="T058 Live Gate")

    boundary_context = _principal(
        tenant_b,
        subject="t058-boundary-seeder",
        identity_type=IdentityType.SERVICE,
        roles=frozenset({"service"}),
    )
    with PostgresUnitOfWork(
        lambda: psycopg.connect(settings["RECLAIM_DATABASE_URL"]),
        authorization_context=boundary_context,
    ) as unit_of_work:
        unit_of_work.tenants.create(
            tenant_id=tenant_b, display_name="T058 Boundary Tenant"
        )

    minio_store = ImmutableEvidenceStore.from_endpoint(
        settings["RECLAIM_MINIO_ENDPOINT"],
        access_key=settings["RECLAIM_MINIO_ACCESS_KEY"],
        secret_key=settings["RECLAIM_MINIO_SECRET_KEY"],
    )
    intake_service = IncidentIntakeService(
        unit_of_work_factory=factory,
        raw_report_store=minio_store,
    )
    verifier = OIDCVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        signing_key=SIGNING_KEY,
        algorithms=("HS256",),
    )
    from api.intake import create_intake_app

    app = create_intake_app(intake_service=intake_service, oidc_verifier=verifier)
    intake = _intake_request(
        tenant_id,
        key=f"t058-canonical-{uuid4().hex}",
        received_at=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
    )
    with TestClient(app) as client:
        accepted = client.post(
            f"/tenants/{tenant_id}/incidents",
            json=intake.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {_token(tenant_id)}"},
        )
        duplicate = client.post(
            f"/tenants/{tenant_id}/incidents",
            json=intake.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {_token(tenant_id)}"},
        )
        denied = client.post(
            f"/tenants/{tenant_b}/incidents",
            json=intake.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {_token(tenant_id)}"},
        )
    assert accepted.status_code == 200
    assert duplicate.status_code == 200
    assert accepted.json()["status"] == IntakeStatus.ACCEPTED.value
    assert duplicate.json()["status"] == IntakeStatus.DUPLICATE.value
    assert denied.status_code == 403
    case_id = accepted.json()["case_id"]
    assert case_id == duplicate.json()["case_id"]

    webhook_processor = WebhookProcessingService(
        verifier=RazorpayWebhookVerifier(
            configured_tenant_id=tenant_id,
            connector_id="razorpay-test",
            secret_resolver=lambda **_: WEBHOOK_SECRET,
        ),
        unit_of_work_factory=factory,
        raw_payload_store=minio_store,
        id_factory=lambda prefix: f"{prefix}-{uuid4().hex}",
    )
    webhook_payload = json.dumps(
        {
            "id": f"evt-{uuid4().hex}",
            "type": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay-{uuid4().hex}",
                        "order_id": f"order-{uuid4().hex}",
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode()
    webhook_payload_data = json.loads(webhook_payload)
    provider_event_id = webhook_payload_data["id"]
    provider_payment_id = webhook_payload_data["payload"]["payment"]["entity"]["id"]
    provider_order_id = webhook_payload_data["payload"]["payment"]["entity"]["order_id"]
    with PostgresUnitOfWork(
        lambda: psycopg.connect(settings["RECLAIM_DATABASE_URL"]),
        authorization_context=service_context,
    ) as unit_of_work:
        unit_of_work.connectors.create(
            connector_id="razorpay-test",
            contract_version="2.0.0",
            connector_type="evidence",
            allowed_resources=("payments",),
            allowed_operations=("read",),
            auth_scope=("merchant:payments:read",),
            credential_scope_ref=(
                f"secret/data/tenants/{tenant_id}/connectors/razorpay-test/webhook"
            ),
            schema_version="1.0.0",
            failure_state_version="1.0.0",
            mode="simulator",
        )
        unit_of_work.provider_correlations.register(
            mapping_id=f"mapping-{uuid4().hex}",
            provider="razorpay",
            connector_id="razorpay-test",
            provider_event_id=provider_event_id,
            provider_payment_id=provider_payment_id,
            provider_order_id=provider_order_id,
            incident_id=accepted.json()["incident_id"],
            case_id=case_id,
            related_order_reference=f"merchant://orders/{provider_order_id}",
            related_payment_reference=f"merchant://payments/{provider_payment_id}",
            mapping_source="merchant_order_payment_context",
            mapping_source_reference=f"merchant://orders/{provider_order_id}",
            mapping_source_checksum="sha256:t058-trusted-order-payment-context",
            verified_at=datetime(2026, 8, 30, 9, 45, tzinfo=UTC),
        )
    webhook_signature = hmac.new(
        WEBHOOK_SECRET.encode(), webhook_payload, hashlib.sha256
    ).hexdigest()
    webhook = _webhook_request(
        tenant_id=tenant_id,
        provider_event_id=provider_event_id,
        signature=webhook_signature,
        payload=webhook_payload,
        correlation_id=intake.correlation_id,
    )
    valid_webhook = webhook_processor.process(
        webhook,
        authorization_context=user_context,
        case_id=case_id,
    )
    duplicate_webhook = webhook_processor.process(
        webhook,
        authorization_context=user_context,
        case_id=case_id,
    )
    invalid_webhook = webhook_processor.process(
        webhook.model_copy(
            update={
                "signature": "invalid-signature",
                "provider_event_id": "evt-invalid",
            }
        ),
        authorization_context=user_context,
        case_id=case_id,
    )
    assert valid_webhook.status is IntakeStatus.ACCEPTED
    assert duplicate_webhook.status is IntakeStatus.DUPLICATE
    assert invalid_webhook.status is IntakeStatus.QUARANTINED

    evidence_storage = EvidenceStorage(minio_store)
    orchestrator = EvidenceOrchestrator(
        build_default_evidence_simulators(tenant_id),
        storage=evidence_storage,
        unit_of_work_factory=factory,
    )
    assert build_razorpay_test_mode_manifest(tenant_id).label == "replay"

    partial_case = intake_service.accept(
        _intake_request(
            tenant_id,
            key=f"t058-partial-{uuid4().hex}",
            received_at=datetime(2026, 8, 30, 10, 3, tzinfo=UTC),
        ),
        authorization_context=user_context,
    )
    partial_connectors = build_default_evidence_simulators(
        tenant_id,
        scenarios={
            "sessions": EvidenceSimulatorScenario.PARTIAL,
            "payments": EvidenceSimulatorScenario.UNAVAILABLE,
        },
    )
    partial_orchestrator = EvidenceOrchestrator(
        partial_connectors,
        storage=evidence_storage,
        unit_of_work_factory=factory,
    )
    partial_requests = tuple(
        request
        for request in _evidence_requests(
            partial_orchestrator,
            tenant_id=tenant_id,
            case_id=partial_case.case_id or "",
            correlation_id=f"corr-{partial_case.case_id}",
        )
        if request.resource_type in {"sessions", "payments"}
    )
    partial_result = partial_orchestrator.collect(
        case_id=partial_case.case_id or "",
        requests=partial_requests,
        authorization_context=user_context,
    )
    unavailable = next(
        item for item in partial_result.items if item.resource_type == "payments"
    )
    assert unavailable.normalized_facts == ()
    assert unavailable.collection_error is not None
    assert partial_result.uncertainty
    partial_timeline = TimelineReconstructor(unit_of_work_factory=factory).rebuild(
        case_id=partial_case.case_id or "",
        evidence=partial_result.items,
        normalized_facts=partial_result.normalized_facts,
        authorization_context=user_context,
    )
    assert len(partial_timeline.events) == 1

    temporal_client = await Client.connect(settings["RECLAIM_TEMPORAL_TARGET"])
    temporal_queue = f"t058-gate-{uuid4().hex}"
    timeline_reconstructor = TimelineReconstructor(unit_of_work_factory=factory)
    worker_dependencies = CaseWorkerDependencies(
        unit_of_work_factory=factory,
        authorization_context_factory=lambda value: _principal(
            value,
            subject="t058-service",
            identity_type=IdentityType.SERVICE,
            roles=frozenset({"service"}),
        ),
        evidence_orchestrator=orchestrator,
        evidence_storage=evidence_storage,
        timeline_reconstructor=timeline_reconstructor,
    )
    workflow_command = CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=intake.correlation_id,
        command_id=f"t058-command-{uuid4().hex}",
    )
    command_service = CaseWorkflowCommandService(
        temporal_client=temporal_client,
        unit_of_work_factory=factory,
        task_queue=temporal_queue,
    )
    async with create_case_worker(
        temporal_client,
        worker_dependencies,
        task_queue=temporal_queue,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        started = await command_service.start_case(
            workflow_command,
            authorization_context=user_context,
        )
        temporal_result = await temporal_client.get_workflow_handle(
            started.workflow_id
        ).result()
    assert started.started is True
    assert temporal_result["completed_stages"] == [
        "collect_evidence",
        "rebuild_timeline",
    ]
    assert temporal_result["authoritative_state"] == "timeline_ready"
    with psycopg.connect(settings["RECLAIM_DATABASE_URL"]) as connection:
        case_state = connection.execute(
            "SELECT current_state FROM cases WHERE tenant_id = %s AND case_id = %s",
            (tenant_id, case_id),
        ).fetchone()
        raw_report_reference = connection.execute(
            "SELECT raw_input_reference FROM incidents WHERE tenant_id = %s AND incident_id = %s",
            (tenant_id, accepted.json()["incident_id"]),
        ).fetchone()[0]
        counts_before_delivery = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM incidents WHERE tenant_id = %s),
                (SELECT count(*) FROM cases WHERE tenant_id = %s),
                (SELECT count(*) FROM evidence_items WHERE tenant_id = %s),
                (SELECT count(*) FROM timeline_events WHERE tenant_id = %s),
                (SELECT count(*) FROM outbox_events WHERE tenant_id = %s),
                (SELECT count(*) FROM audit_records WHERE tenant_id = %s)
            """,
            (tenant_id,) * 6,
        ).fetchone()
        audit_chain = connection.execute(
            "SELECT previous_record_checksum, record_checksum FROM audit_records WHERE tenant_id = %s ORDER BY chain_sequence",
            (tenant_id,),
        ).fetchall()
    assert case_state == ("timeline_ready",)
    parsed_report_reference = json.loads(raw_report_reference)
    report_path = urlsplit(parsed_report_reference["reference_id"]).path.lstrip("/")
    assert report_path.startswith(f"tenants/{tenant_id}/")
    report_object_name = report_path.removeprefix(f"tenants/{tenant_id}/")
    stored_report, report_content = minio_store.get_verified(
        tenant_id=tenant_id,
        object_name=report_object_name,
    )
    assert stored_report.checksum == parsed_report_reference["checksum"]
    assert json.loads(report_content)["report_content"] == intake.report_content
    assert counts_before_delivery == (2, 2, 8, 7, 13, 6)
    assert audit_chain[0][0] is None
    assert all(
        previous == audit_chain[index - 1][1]
        for index, (previous, _) in enumerate(audit_chain)
        if index
    )

    from aiokafka import AIOKafkaProducer
    from app.events.redpanda import RedpandaOutboxPublisher

    producer = AIOKafkaProducer(bootstrap_servers=settings["RECLAIM_REDPANDA_BROKERS"])
    await producer.start()
    projection = Neo4jCaseProjection.from_uri(
        settings["RECLAIM_NEO4J_URI"],
        username=settings["RECLAIM_NEO4J_USER"],
        password=settings["RECLAIM_NEO4J_PASSWORD"],
    )
    projection.bootstrap()
    projection_consumer = Neo4jCaseProjectionConsumer(projection)
    projection_events: list[Any] = []
    try:
        published = await RedpandaOutboxPublisher(producer).publish_pending(
            unit_of_work_factory=factory,
            authorization_context=service_context,
        )
        assert len(published) == 13
        received = await _consume_events(
            topic="reclaim.domain.v1",
            expected_event_ids={event.event_id for event in published},
            database_url=settings["RECLAIM_DATABASE_URL"],
            service_context=service_context,
            projection_consumer=projection_consumer,
            projection_events=projection_events,
        )
        assert {event.event_id for event in received} == {
            event.event_id for event in published
        }
        assert len(projection_events) == 12

        duplicate_result = await projection_consumer.dispatch(
            serialize_event(projection_events[0]),
            unit_of_work_factory=factory,
            authorization_context=service_context,
        )
        assert duplicate_result.processed is False

        counts_after_delivery = counts_before_delivery
        rebuilt = projection.rebuild(tenant_id, tuple(reversed(projection_events)))
        assert rebuilt.applied_events == 12
        assert projection.checkpoints(tenant_id)
        with psycopg.connect(settings["RECLAIM_DATABASE_URL"]) as connection:
            counts_after_delivery = connection.execute(
                "SELECT count(*) FROM incidents WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        assert counts_after_delivery == (2,)

        from app.events.incident_events import build_incident_accepted_event

        foreign = build_incident_accepted_event(
            tenant_id=tenant_b,
            correlation_id="corr-foreign",
            incident_id="foreign-incident",
            case_id="foreign-case",
            source="operator",
            received_at=datetime(2026, 8, 30, 11, tzinfo=UTC),
            report_reference=None,
            report_content_present=False,
            causation_id="foreign",
            producer="test",
        )
        with pytest.raises(EventTransportError, match="tenant"):
            await projection_consumer.dispatch(
                serialize_event(foreign),
                unit_of_work_factory=factory,
                authorization_context=service_context,
            )
    finally:
        projection.reset_tenant(tenant_id)
        projection.close()
        await producer.stop()

    assert temporal_result["case_id"] == case_id
