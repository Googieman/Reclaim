"""Live PostgreSQL checks for D3 provider-correlation authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.provider_correlations import (
    ProviderCorrelationMappingConflictError,
)
from app.db.unit_of_work import PostgresUnitOfWork
from app.intake.webhook_processing import WebhookProcessingService
from app.storage.minio_evidence import checksum_for_bytes
from connectors.razorpay.webhook import RazorpayWebhookVerifier
from packages.contracts.intake import IntakeStatus, RazorpayWebhookRequest


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 30, 9, tzinfo=UTC)
SECRET = "d3-postgres-test-secret"


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_id: str
    connector_id: str
    incident_id: str
    case_id: str
    other_incident_id: str
    other_case_id: str
    mapping_id: str
    provider_event_id: str
    provider_payment_id: str
    provider_order_id: str
    merchant_reference: str


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_name: str


class RecordingRawStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, **values: object) -> StoredObject:
        object_name = str(values["object_name"])
        content = bytes(values["content"])
        assert values["expected_checksum"] == checksum_for_bytes(content)
        self.objects[object_name] = content
        return StoredObject(object_name)


def _database_url() -> str:
    value = os.getenv("RECLAIM_DATABASE_URL")
    if not value:
        pytest.skip("RECLAIM_DATABASE_URL is required for D3 PostgreSQL validation")
    return value


def _context(tenant_id: str):
    principal = AuthenticatedPrincipal(
        subject="d3-postgres-test",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="d3-test-issuer",
    )
    return principal.for_tenant(tenant_id)


def _factory(database_url: str):
    import psycopg

    return lambda context: PostgresUnitOfWork(
        lambda: psycopg.connect(database_url), authorization_context=context
    )


def _seed(database_url: str, *, prefix: str) -> Seed:
    suffix = uuid4().hex
    tenant_id = f"{prefix}-tenant-{suffix}"
    connector_id = "razorpay-test"
    incident_id = f"{prefix}-incident-{suffix}"
    case_id = f"{prefix}-case-{suffix}"
    other_incident_id = f"{prefix}-other-incident-{suffix}"
    other_case_id = f"{prefix}-other-case-{suffix}"
    mapping_id = f"{prefix}-mapping-{suffix}"
    provider_event_id = f"{prefix}-event-{suffix}"
    provider_payment_id = f"{prefix}-payment-{suffix}"
    provider_order_id = f"{prefix}-order-{suffix}"
    merchant_reference = f"{prefix}-merchant-ref-{suffix}"
    context = _context(tenant_id)
    factory = _factory(database_url)

    with factory(context) as unit_of_work:
        unit_of_work.tenants.create(
            tenant_id=tenant_id, display_name=f"D3 {prefix} tenant"
        )
    with factory(context) as unit_of_work:
        unit_of_work.connectors.create(
            connector_id=connector_id,
            contract_version="2.0.0",
            connector_type="evidence",
            allowed_resources=("payments",),
            allowed_operations=("read",),
            auth_scope=("merchant:payments:read",),
            credential_scope_ref=(
                f"secret/data/tenants/{tenant_id}/connectors/{connector_id}/webhook"
            ),
            schema_version="1.0.0",
            failure_state_version="1.0.0",
            mode="simulator",
        )
        unit_of_work.incidents.create(
            incident_id=incident_id,
            source="d3-test",
            reporter_context={"provenance": "synthetic"},
            received_at=NOW,
            correlation_key=f"correlation-{suffix}",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity=f"dedupe-{suffix}",
        )
        unit_of_work.cases.create(
            case_id=case_id, incident_id=incident_id, created_at=NOW
        )
        unit_of_work.incidents.create(
            incident_id=other_incident_id,
            source="d3-test",
            reporter_context={"provenance": "synthetic"},
            received_at=NOW,
            correlation_key=f"other-correlation-{suffix}",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity=f"other-dedupe-{suffix}",
        )
        unit_of_work.cases.create(
            case_id=other_case_id, incident_id=other_incident_id, created_at=NOW
        )
        unit_of_work.provider_correlations.register(
            mapping_id=mapping_id,
            provider="razorpay",
            connector_id=connector_id,
            provider_event_id=provider_event_id,
            provider_payment_id=provider_payment_id,
            provider_order_id=provider_order_id,
            merchant_reference=merchant_reference,
            incident_id=incident_id,
            case_id=case_id,
            related_order_reference=f"merchant://orders/{provider_order_id}",
            related_payment_reference=f"merchant://payments/{provider_payment_id}",
            mapping_source="merchant_order_payment_context",
            mapping_source_reference=f"merchant://orders/{provider_order_id}",
            mapping_source_checksum="sha256:d3-trusted-context",
            verified_at=NOW,
        )
    return Seed(
        tenant_id,
        connector_id,
        incident_id,
        case_id,
        other_incident_id,
        other_case_id,
        mapping_id,
        provider_event_id,
        provider_payment_id,
        provider_order_id,
        merchant_reference,
    )


def _cleanup(database_url: str, seeds: tuple[Seed, ...]) -> None:
    import psycopg

    tenant_ids = tuple(seed.tenant_id for seed in seeds)
    with psycopg.connect(database_url) as connection:
        placeholders = ", ".join(["%s"] * len(tenant_ids))
        connection.execute(
            f"DELETE FROM webhook_deliveries WHERE tenant_id IN ({placeholders})",
            tenant_ids,
        )
        connection.execute(
            f"DELETE FROM webhook_quarantines WHERE tenant_id IN ({placeholders})",
            tenant_ids,
        )
        connection.execute(
            f"DELETE FROM outbox_events WHERE tenant_id IN ({placeholders})",
            tenant_ids,
        )
        connection.execute(
            "ALTER TABLE audit_records DISABLE TRIGGER audit_records_append_only"
        )
        connection.execute(
            f"DELETE FROM audit_records WHERE tenant_id IN ({placeholders})", tenant_ids
        )
        connection.execute(
            "ALTER TABLE audit_records ENABLE TRIGGER audit_records_append_only"
        )
        connection.execute(
            f"DELETE FROM provider_correlation_mappings WHERE tenant_id IN ({placeholders})",
            tenant_ids,
        )
        connection.execute(
            f"DELETE FROM cases WHERE tenant_id IN ({placeholders})", tenant_ids
        )
        connection.execute(
            f"DELETE FROM incidents WHERE tenant_id IN ({placeholders})", tenant_ids
        )
        connection.execute(
            f"DELETE FROM connector_configurations WHERE tenant_id IN ({placeholders})",
            tenant_ids,
        )
        connection.execute(
            f"DELETE FROM tenants WHERE tenant_id IN ({placeholders})", tenant_ids
        )


def _payload(seed: Seed, *, event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "entity": "event",
            "id": event_id or seed.provider_event_id,
            "type": "payment.captured",
            "created_at": int(NOW.timestamp()),
            "payload": {
                "payment": {
                    "entity": {
                        "id": seed.provider_payment_id,
                        "order_id": seed.provider_order_id,
                        "notes": {"merchant_reference": seed.merchant_reference},
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode()


def _request(
    seed: Seed, *, tenant_id: str | None = None, event_id: str | None = None
) -> RazorpayWebhookRequest:
    payload = _payload(seed, event_id=event_id)
    actual_event_id = event_id or seed.provider_event_id
    return RazorpayWebhookRequest(
        tenant_id=tenant_id or seed.tenant_id,
        correlation_id=f"corr-{actual_event_id}",
        connector_id=seed.connector_id,
        original_payload=payload,
        payload_checksum=checksum_for_bytes(payload),
        signature=hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest(),
        provider_event_id=actual_event_id,
        event_type="payment.captured",
        event_timestamp=NOW,
        received_at=NOW + timedelta(minutes=1),
    )


def _processor(
    database_url: str, seed: Seed
) -> tuple[WebhookProcessingService, RecordingRawStore]:
    store = RecordingRawStore()
    processor = WebhookProcessingService(
        verifier=RazorpayWebhookVerifier(
            configured_tenant_id=seed.tenant_id,
            connector_id=seed.connector_id,
            secret_resolver=lambda **_: SECRET,
        ),
        unit_of_work_factory=_factory(database_url),
        raw_payload_store=store,
        id_factory=lambda prefix: f"{prefix}-{uuid4().hex}",
    )
    return processor, store


def _set_tenant(connection, tenant_id: str) -> None:
    connection.execute("SELECT set_config('reclaim.tenant_id', %s, true)", (tenant_id,))


def test_d3_postgres_constraints_and_idempotent_mapping() -> None:
    database_url = _database_url()
    import psycopg

    seed = _seed(database_url, prefix="d3-integrity")
    try:
        context = _context(seed.tenant_id)
        factory = _factory(database_url)
        with factory(context) as unit_of_work:
            duplicate, inserted = unit_of_work.provider_correlations.register(
                mapping_id=f"duplicate-{uuid4().hex}",
                provider="razorpay",
                connector_id=seed.connector_id,
                provider_event_id=seed.provider_event_id,
                provider_payment_id=seed.provider_payment_id,
                provider_order_id=seed.provider_order_id,
                merchant_reference=seed.merchant_reference,
                incident_id=seed.incident_id,
                case_id=seed.case_id,
                related_order_reference=f"merchant://orders/{seed.provider_order_id}",
                related_payment_reference=f"merchant://payments/{seed.provider_payment_id}",
                mapping_source="merchant_order_payment_context",
                mapping_source_reference=f"merchant://orders/{seed.provider_order_id}",
                mapping_source_checksum="sha256:d3-trusted-context",
                verified_at=NOW,
            )
            assert duplicate.mapping_id == seed.mapping_id
            assert inserted is False

            with pytest.raises(ProviderCorrelationMappingConflictError):
                unit_of_work.provider_correlations.register(
                    mapping_id=f"conflict-{uuid4().hex}",
                    provider="razorpay",
                    connector_id=seed.connector_id,
                    provider_payment_id=seed.provider_payment_id,
                    provider_order_id="different-order",
                    incident_id=seed.other_incident_id,
                    case_id=seed.other_case_id,
                    mapping_source="merchant_order_payment_context",
                    mapping_source_reference="merchant://orders/different-order",
                    mapping_source_checksum="sha256:different-context",
                    verified_at=NOW,
                )

        with psycopg.connect(database_url) as connection:
            _set_tenant(connection, seed.tenant_id)
            connection.execute("SAVEPOINT d3_unique")
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO provider_correlation_mappings (
                        tenant_id, mapping_id, provider, connector_id,
                        provider_event_id, provider_payment_id, provider_order_id,
                        incident_id, case_id, mapping_source, mapping_source_reference,
                        mapping_source_checksum, verified_at
                    ) VALUES (%s, %s, 'razorpay', %s, %s, %s, %s, %s, %s,
                              'merchant_order_payment_context', 'direct-test',
                              'sha256:direct-test', %s)
                    """,
                    (
                        seed.tenant_id,
                        f"direct-collision-{uuid4().hex}",
                        seed.connector_id,
                        f"different-event-{uuid4().hex}",
                        seed.provider_payment_id,
                        f"different-order-{uuid4().hex}",
                        seed.incident_id,
                        seed.case_id,
                        NOW,
                    ),
                )
            connection.execute("ROLLBACK TO SAVEPOINT d3_unique")
            connection.execute("SAVEPOINT d3_owner")
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                connection.execute(
                    """
                    INSERT INTO provider_correlation_mappings (
                        tenant_id, mapping_id, provider, connector_id,
                        provider_payment_id, incident_id, case_id, mapping_source,
                        mapping_source_reference, mapping_source_checksum, verified_at
                    ) VALUES (%s, %s, 'razorpay', %s, %s, %s, %s,
                              'server_preregistration', 'direct-test',
                              'sha256:direct-test', %s)
                    """,
                    (
                        seed.tenant_id,
                        f"direct-owner-mismatch-{uuid4().hex}",
                        seed.connector_id,
                        f"new-payment-{uuid4().hex}",
                        seed.incident_id,
                        seed.other_case_id,
                        NOW,
                    ),
                )
            connection.execute("ROLLBACK TO SAVEPOINT d3_owner")
            connection.execute("SAVEPOINT d3_identity")
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    INSERT INTO provider_correlation_mappings (
                        tenant_id, mapping_id, provider, connector_id, incident_id,
                        case_id, mapping_source, mapping_source_reference,
                        mapping_source_checksum, verified_at
                    ) VALUES (%s, %s, 'razorpay', %s, %s, %s,
                              'server_preregistration', 'direct-test',
                              'sha256:direct-test', %s)
                    """,
                    (
                        seed.tenant_id,
                        f"direct-no-identity-{uuid4().hex}",
                        seed.connector_id,
                        seed.incident_id,
                        seed.case_id,
                        NOW,
                    ),
                )
            connection.execute("ROLLBACK TO SAVEPOINT d3_identity")
    finally:
        _cleanup(database_url, (seed,))


def test_d3_processing_resolves_only_mapped_identity_and_quarantines_substitution() -> (
    None
):
    database_url = _database_url()
    seed = _seed(database_url, prefix="d3-processing")
    other_seed = _seed(database_url, prefix="d3-other")
    try:
        processor, _ = _processor(database_url, seed)
        context = _context(seed.tenant_id)
        accepted = processor.process(_request(seed), authorization_context=context)
        duplicate = processor.process(_request(seed), authorization_context=context)
        arbitrary_case = processor.process(
            _request(seed, event_id=f"unknown-{uuid4().hex}"),
            authorization_context=context,
            case_id=seed.other_case_id,
        )
        conflicting_assertion = processor.process(
            _request(seed), authorization_context=context, case_id=seed.other_case_id
        )
        cross_tenant = processor.process(
            _request(other_seed, tenant_id=seed.tenant_id),
            authorization_context=context,
            incident_id=other_seed.incident_id,
            case_id=other_seed.case_id,
        )

        assert accepted.status is IntakeStatus.ACCEPTED
        assert accepted.authoritative_mapping_id == seed.mapping_id
        assert (accepted.incident_id, accepted.case_id) == (
            seed.incident_id,
            seed.case_id,
        )
        assert duplicate.status is IntakeStatus.DUPLICATE
        assert duplicate.authoritative_mapping_id == seed.mapping_id
        assert arbitrary_case.status is IntakeStatus.QUARANTINED
        assert arbitrary_case.reason == "unresolved_association"
        assert arbitrary_case.case_id is None
        assert conflicting_assertion.status is IntakeStatus.QUARANTINED
        assert conflicting_assertion.reason == "assertion_mismatch"
        assert cross_tenant.status is IntakeStatus.QUARANTINED
        assert cross_tenant.reason == "unresolved_association"

        import psycopg

        with psycopg.connect(database_url) as connection:
            _set_tenant(connection, seed.tenant_id)
            assert connection.execute(
                """
                SELECT authoritative_mapping_id, incident_id, case_id
                FROM webhook_deliveries
                WHERE tenant_id = %s AND connector_id = %s AND provider_event_id = %s
                """,
                (seed.tenant_id, seed.connector_id, seed.provider_event_id),
            ).fetchone() == (seed.mapping_id, seed.incident_id, seed.case_id)
            quarantine_rows = connection.execute(
                """
                SELECT association_status, verified_correlation->>'provider_payment_id'
                FROM webhook_quarantines
                WHERE tenant_id = %s
                ORDER BY created_at, quarantine_id
                """,
                (seed.tenant_id,),
            ).fetchall()
            assert (
                "unresolved_association",
                seed.provider_payment_id,
            ) in quarantine_rows
            assert ("assertion_mismatch", seed.provider_payment_id) in quarantine_rows
            event_types = connection.execute(
                "SELECT event_type FROM outbox_events WHERE tenant_id = %s",
                (seed.tenant_id,),
            ).fetchall()
            assert all(
                event_type == ("webhook.quarantined",) for event_type in event_types
            )
            assert connection.execute(
                "SELECT current_state FROM cases WHERE tenant_id = %s AND case_id = %s",
                (seed.tenant_id, seed.other_case_id),
            ).fetchone() == ("intake_received",)
    finally:
        _cleanup(database_url, (seed, other_seed))


def test_d3_non_owner_rls_isolation_for_provider_mappings() -> None:
    database_url = _database_url()
    rls_url = os.getenv("RECLAIM_RLS_DATABASE_URL")
    if not rls_url:
        pytest.skip("RECLAIM_RLS_DATABASE_URL is required for D3 RLS validation")
    seed_a = _seed(database_url, prefix="d3-rls-a")
    seed_b = _seed(database_url, prefix="d3-rls-b")
    try:
        import psycopg

        with psycopg.connect(rls_url) as connection:
            _set_tenant(connection, seed_a.tenant_id)
            assert connection.execute(
                """
                SELECT mapping_id, tenant_id
                FROM provider_correlation_mappings
                WHERE tenant_id IN (%s, %s)
                ORDER BY mapping_id
                """,
                (seed_a.tenant_id, seed_b.tenant_id),
            ).fetchall() == [(seed_a.mapping_id, seed_a.tenant_id)]
            assert connection.execute(
                "SELECT count(*) FROM provider_correlation_mappings WHERE tenant_id = %s",
                (seed_b.tenant_id,),
            ).fetchone() == (0,)

            connection.execute("SAVEPOINT d3_rls_insert")
            with pytest.raises(psycopg.Error):
                connection.execute(
                    """
                    INSERT INTO provider_correlation_mappings (
                        tenant_id, mapping_id, provider, connector_id,
                        provider_payment_id, incident_id, case_id, mapping_source,
                        mapping_source_reference, mapping_source_checksum, verified_at
                    ) VALUES (%s, %s, 'razorpay', %s, %s, %s, %s,
                              'server_preregistration', 'rls-test', 'sha256:rls-test', %s)
                    """,
                    (
                        seed_b.tenant_id,
                        f"rls-write-{uuid4().hex}",
                        seed_b.connector_id,
                        f"rls-payment-{uuid4().hex}",
                        seed_b.incident_id,
                        seed_b.case_id,
                        NOW,
                    ),
                )
            connection.execute("ROLLBACK TO SAVEPOINT d3_rls_insert")
            assert (
                connection.execute(
                    "UPDATE provider_correlation_mappings SET mapping_status = 'revoked' WHERE tenant_id = %s",
                    (seed_b.tenant_id,),
                ).rowcount
                == 0
            )
    finally:
        _cleanup(database_url, (seed_a, seed_b))
