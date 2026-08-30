"""Focused Remediation Batch C tests for payload and immutable-write boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.intake.service import IncidentIntakeService, IntakePayloadTooLarge
from app.intake.webhook_processing import WebhookProcessingService
from app.payload_limits import PayloadLimitError, enforce_payload_limit
from app.storage.minio_evidence import (
    ImmutableEvidenceStore,
    ObjectIntegrityError,
    ObjectPayloadLimitError,
    checksum_for_bytes,
)
from connectors.evidence.base import (
    EvidencePayloadLimitError,
    EvidenceReadResult,
    ReadOnlyEvidenceAdapter,
)
from connectors.razorpay.webhook import RazorpayWebhookVerifier, payload_checksum
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from packages.contracts.connectors import (
    ConnectorFailureState,
    ConnectorLimits,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
    EvidenceRequest,
    EvidenceResponse,
)
from packages.contracts.intake import (
    IncidentIntakeRequest,
    IntakeStatus,
    RazorpayWebhookRequest,
)


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
SECRET = "batch-c-test-secret"


def reviewer_context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="batch-c-reviewer",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def incident_request(
    content: str, *, key: str = "batch-c-intake"
) -> IncidentIntakeRequest:
    return IncidentIntakeRequest(
        tenant_id="tenant-a",
        correlation_id=f"corr-{key}",
        source="operator",
        received_at=NOW,
        reporter_context={"channel": "test"},
        report_content=content,
        idempotency_key=key,
    )


def test_payload_limit_accepts_exact_bytes_and_rejects_one_byte_over() -> None:
    enforce_payload_limit(b"x" * 4, max_bytes=4, label="test")

    with pytest.raises(PayloadLimitError, match="exceeds configured size limit"):
        enforce_payload_limit(b"x" * 5, max_bytes=4, label="test")


def test_http_body_limit_rejects_before_fastapi_request_parsing() -> None:
    from api.intake import create_intake_app
    from fastapi.testclient import TestClient

    app = create_intake_app(
        intake_service=object(),  # type: ignore[arg-type]
        oidc_verifier=object(),  # type: ignore[arg-type]
        max_request_body_bytes=8,
    )
    with TestClient(app) as client:
        response = client.post(
            "/tenants/tenant-a/incidents",
            content=b"x" * 9,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json() == {"detail": "request body exceeds configured size limit"}


def test_oversized_incident_report_has_no_transaction_or_object_side_effect() -> None:
    from backend.tests.integration.test_intake_service import (
        MemoryState,
        MemoryUnitOfWork,
        authorization_context,
    )

    accepted_state = MemoryState()
    accepted_service = IncidentIntakeService(
        unit_of_work_factory=lambda context: MemoryUnitOfWork(accepted_state),
        raw_report_store=accepted_state.raw_report_store,
        max_report_bytes=4,
        id_factory=lambda prefix: f"{prefix}-accepted",
    )
    accepted = accepted_service.accept(
        incident_request("four", key="batch-c-exact"),
        authorization_context=authorization_context(),
    )
    assert accepted.status is IntakeStatus.ACCEPTED
    assert len(accepted_state.raw_report_store.client.objects) == 1

    rejected_state = MemoryState()
    factory_calls: list[Any] = []

    def unexpected_factory(_context: object) -> object:
        factory_calls.append(_context)
        raise AssertionError(
            "oversized report must be rejected before opening a transaction"
        )

    rejected_service = IncidentIntakeService(
        unit_of_work_factory=unexpected_factory,  # type: ignore[arg-type]
        raw_report_store=rejected_state.raw_report_store,
        max_report_bytes=4,
    )
    with pytest.raises(IntakePayloadTooLarge, match="exceeds configured size limit"):
        rejected_service.accept(
            incident_request("five!", key="batch-c-over"),
            authorization_context=authorization_context(),
        )

    assert factory_calls == []
    assert rejected_state.raw_report_store.client.objects == {}


def webhook_request(
    payload: bytes, *, correlation_id: str = "corr-webhook"
) -> RazorpayWebhookRequest:
    return RazorpayWebhookRequest(
        tenant_id="tenant-a",
        correlation_id=correlation_id,
        connector_id="razorpay-test",
        original_payload=payload,
        payload_checksum=payload_checksum(payload),
        signature=hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest(),
        provider_event_id="evt-batch-c",
        event_type="payment.captured",
        event_timestamp=NOW,
        received_at=NOW,
    )


def webhook_verifier(limit: int) -> RazorpayWebhookVerifier:
    return RazorpayWebhookVerifier(
        configured_tenant_id="tenant-a",
        connector_id="razorpay-test",
        secret_resolver=lambda **_: SECRET,
        max_payload_bytes=limit,
    )


def test_webhook_raw_limit_is_exact_and_checked_before_json_parsing() -> None:
    payload = json.dumps(
        {"id": "evt-batch-c", "type": "payment.captured"}, separators=(",", ":")
    ).encode()
    exact = webhook_verifier(len(payload)).verify(
        webhook_request(payload), authorization_context=reviewer_context()
    )
    assert exact.status is IntakeStatus.ACCEPTED

    oversized_payload = payload + b"x"
    oversized = webhook_verifier(len(payload)).verify(
        webhook_request(oversized_payload), authorization_context=reviewer_context()
    )
    assert oversized.status is IntakeStatus.QUARANTINED
    assert oversized.payload_size_exceeded is True
    assert oversized.reason == "webhook payload exceeds configured size limit"


def test_oversized_webhook_has_no_quarantine_storage_uow_or_outbox_side_effect() -> (
    None
):
    payload = b"x" * 9
    raw_objects: list[bytes] = []
    factory_calls: list[Any] = []

    class RawStore:
        def put(self, **values: object) -> object:
            raw_objects.append(bytes(values["content"]))
            raise AssertionError("oversized webhook must not write raw evidence")

    def unexpected_factory(_context: object) -> object:
        factory_calls.append(_context)
        raise AssertionError("oversized webhook must not open a transaction")

    processor = WebhookProcessingService(
        verifier=webhook_verifier(8),
        unit_of_work_factory=unexpected_factory,  # type: ignore[arg-type]
        raw_payload_store=RawStore(),  # type: ignore[arg-type]
        id_factory=lambda prefix: prefix,
    )
    result = processor.process(
        webhook_request(payload), authorization_context=reviewer_context()
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "webhook payload exceeds configured size limit"
    assert raw_objects == []
    assert factory_calls == []


def evidence_manifest(*, max_payload_bytes: int) -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id="tenant-a",
        correlation_id="corr-evidence",
        connector_id="sessions-simulator",
        contract_version="1.0.0",
        connector_type=ConnectorType.EVIDENCE,
        mode=ConnectorMode.SIMULATOR,
        resources=("sessions",),
        operations=("read",),
        auth_scope=("merchant:sessions:read",),
        request_schema="evidence.sessions.request.v1",
        response_schema="evidence.sessions.response.v1",
        limits=ConnectorLimits(max_payload_bytes=max_payload_bytes),
        timestamp_semantics="observed_at then collected_at",
        idempotency_behavior="duplicate reads are replay-safe",
        failure_states=tuple(ConnectorFailureState),
    )


def evidence_request() -> EvidenceRequest:
    return EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-evidence",
        case_id="case-batch-c",
        connector_id="sessions-simulator",
        resource_type="sessions",
        requested_at=NOW,
    )


def evidence_response() -> EvidenceResponse:
    return EvidenceResponse(
        tenant_id="tenant-a",
        correlation_id="corr-evidence",
        case_id="case-batch-c",
        connector_id="sessions-simulator",
        source_identity="merchant-session-store",
        resource_type="sessions",
        observed_at=NOW,
        collected_at=NOW,
        completeness="complete",
        normalized_facts=[],
        connector_status="complete",
    )


def test_connector_response_limit_is_enforced_before_evidence_storage() -> None:
    request = evidence_request()
    response = evidence_response()
    exact_adapter = ReadOnlyEvidenceAdapter(
        evidence_manifest(max_payload_bytes=4),
        reader=lambda _: EvidenceReadResult(response, b"1234"),
    )
    assert (
        exact_adapter.read(
            request, authorization_context=reviewer_context()
        ).raw_payload
        == b"1234"
    )

    oversized_adapter = ReadOnlyEvidenceAdapter(
        evidence_manifest(max_payload_bytes=4),
        reader=lambda _: EvidenceReadResult(response, b"12345"),
    )
    with pytest.raises(
        EvidencePayloadLimitError, match="exceeds declared payload limit"
    ):
        oversized_adapter.read(request, authorization_context=reviewer_context())

    object_storage = InMemoryObjectStorage()
    calls: list[Any] = []

    def unexpected_factory(_context: object) -> object:
        calls.append(_context)
        raise AssertionError("oversized connector output must not persist metadata")

    orchestrator = EvidenceOrchestrator(
        {"sessions-simulator": oversized_adapter},
        storage=EvidenceStorage(ImmutableEvidenceStore(object_storage)),
        unit_of_work_factory=unexpected_factory,  # type: ignore[arg-type]
    )
    with pytest.raises(EvidencePayloadLimitError):
        orchestrator.collect(
            case_id="case-batch-c",
            requests=(request,),
            authorization_context=reviewer_context(),
        )
    assert object_storage.objects == {}
    assert calls == []


def test_raw_object_limit_is_enforced_at_storage_boundary() -> None:
    object_storage = InMemoryObjectStorage()
    store = ImmutableEvidenceStore(object_storage, max_payload_bytes=4)
    stored = store.put(tenant_id="tenant-a", object_name="exact.bin", content=b"1234")
    assert stored.checksum == checksum_for_bytes(b"1234")

    with pytest.raises(ObjectPayloadLimitError, match="exceeds configured size limit"):
        store.put(tenant_id="tenant-a", object_name="over.bin", content=b"12345")
    assert tuple(object_storage.objects) == ("tenants/tenant-a/exact.bin",)


def test_concurrent_same_content_writes_are_idempotent() -> None:
    store = ImmutableEvidenceStore(InMemoryObjectStorage())

    def write(_: int):
        return store.put(
            tenant_id="tenant-a",
            object_name="case-batch-c/raw.json",
            content=b"same-content",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(write, range(8)))

    assert len(results) == 8
    assert {result.checksum for result in results} == {
        checksum_for_bytes(b"same-content")
    }
    _, content = store.get_verified(
        tenant_id="tenant-a", object_name="case-batch-c/raw.json"
    )
    assert content == b"same-content"


def test_concurrent_conflicting_writes_have_one_owner_and_never_overwrite() -> None:
    store = ImmutableEvidenceStore(InMemoryObjectStorage())
    contents = (b"first-content", b"second-content")

    def write(content: bytes) -> tuple[str, bytes | str]:
        try:
            store.put(
                tenant_id="tenant-a",
                object_name="case-batch-c/conflict.json",
                content=content,
            )
        except ObjectIntegrityError as exc:
            return "error", str(exc)
        return "ok", content

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, contents))

    assert sorted(result[0] for result in results) == ["error", "ok"]
    _, stored_content = store.get_verified(
        tenant_id="tenant-a", object_name="case-batch-c/conflict.json"
    )
    assert stored_content in contents
    assert next(result[1] for result in results if result[0] == "ok") == stored_content


def test_storage_rejects_clients_without_atomic_create_instead_of_falling_back() -> (
    None
):
    class NonAtomicClient:
        def __init__(self) -> None:
            self.put_calls = 0

        def stat_object(self, bucket_name: str, object_name: str) -> object:
            raise AssertionError("stat-then-put is not an atomic strategy")

        def put_object(
            self,
            bucket_name: str,
            object_name: str,
            data: BytesIO,
            length: int,
            **kwargs: object,
        ) -> None:
            self.put_calls += 1

        def get_object(self, bucket_name: str, object_name: str) -> object:
            raise AssertionError("object must not be read after unsupported write")

    client = NonAtomicClient()
    with pytest.raises(ObjectIntegrityError, match="atomic immutable-create"):
        ImmutableEvidenceStore(client).put(
            tenant_id="tenant-a", object_name="unsupported.bin", content=b"content"
        )
    assert client.put_calls == 0


def test_live_minio_atomic_concurrency_if_service_is_configured() -> None:
    endpoint = os.getenv("RECLAIM_MINIO_ENDPOINT")
    access_key = os.getenv("RECLAIM_MINIO_ACCESS_KEY")
    secret_key = os.getenv("RECLAIM_MINIO_SECRET_KEY")
    if not (endpoint and access_key and secret_key):
        pytest.skip("MinIO endpoint and credentials are required for live validation")
    from minio import Minio

    store = ImmutableEvidenceStore(
        Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    )
    object_name = f"batch-c/{uuid4().hex}/conflict.bin"
    contents = (b"live-first", b"live-second")

    def write(content: bytes) -> str:
        try:
            store.put(tenant_id="tenant-a", object_name=object_name, content=content)
        except ObjectIntegrityError:
            return "error"
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(write, contents))
    assert sorted(statuses) == ["error", "ok"]
    _, stored_content = store.get_verified(
        tenant_id="tenant-a", object_name=object_name
    )
    assert stored_content in contents
