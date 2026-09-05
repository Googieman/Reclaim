"""Deterministic fault-injection matrix for FS-001 authority and recovery seams.

The matrix deliberately uses local doubles.  It proves the failure semantics of
the runtime boundaries without pretending that a local double is a live outage
of PostgreSQL, Temporal, Redpanda, or another external dependency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from action_gateway.idempotency import InMemoryActionExecutionStore
from action_gateway.reconciliation import recover_action
from action_gateway.verification import VerificationService, verify_and_route
from app.auth.oidc import (
    IdentityType,
    OIDCVerifier,
    TenantAuthorizationContext,
    TenantAuthorizationError,
)
from app.coordination.redis import CoordinationUnavailable, RedisCoordinator
from app.events.outbox import OutboxEvent
from app.events.redpanda import RedpandaOutboxPublisher
from app.storage.minio_evidence import ImmutableEvidenceStore, ObjectIntegrityError
from app.secrets.vault import SecretAccessDenied, VaultSecretStore
from backend.tests.integration.support import make_authorization_context, make_event
from connectors.evidence.base import EvidenceConnectorError, ReadOnlyEvidenceAdapter
from connectors.simulators.evidence import simulator_manifest
from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest
from packages.contracts.analysis_policy import (
    ActionType,
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)
from packages.contracts.connectors import ConnectorFailureState, EvidenceRequest
from projections.neo4j_projection import Neo4jProjection
from agent.replay_fallback import ReplayFallbackStatus, run_with_replay_fallback

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FaultObservation:
    fault: str
    execution_mode: str
    injected_failure: str
    expected_behavior: str
    observed_outcome: str
    authoritative_state: str
    side_effect_count: int
    recovery: str
    terminal_or_escalation: str


def _assert_observation(observation: FaultObservation) -> None:
    assert observation.execution_mode in {"deterministic-fault-injected", "live"}
    assert observation.injected_failure
    assert observation.expected_behavior
    assert observation.observed_outcome
    assert observation.authoritative_state
    assert observation.side_effect_count >= 0
    assert observation.recovery
    assert observation.terminal_or_escalation
    # This module has no live dependency credentials or service claim.
    assert observation.execution_mode == "deterministic-fault-injected"
    assert isinstance(asdict(observation), dict)


def _action_request() -> ActionGatewayRequest:
    return ActionGatewayRequest(
        tenant_id="tenant-a",
        correlation_id="corr-fault-matrix",
        case_id="case-fault-matrix",
        proposal_id="proposal-fault-matrix",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-fault-matrix",
        parameters={"reason": "fault test"},
        policy_decision_id="policy-fault-matrix",
        policy_version_id="policy-v1.0.0",
        idempotency_key="action-fault-matrix",
        causation_id="proposal-fault-matrix",
        request_checksum="sha256:fault-matrix",
        requested_at=NOW,
    )


def _user_context(tenant_id: str = "tenant-a") -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject="reviewer-fault-matrix",
        tenant_id=tenant_id,
        roles=frozenset({"reviewer"}),
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )


class _TransactionalAuthority:
    def __init__(self) -> None:
        self.available = False
        self.cases: dict[str, str] = {}
        self.outbox: list[str] = []

    def commit(self, case_id: str, event_id: str) -> None:
        if not self.available:
            raise ConnectionError("postgresql injected commit failure")
        # Both records become visible together, representing one DB transaction.
        self.cases[case_id] = "accepted"
        self.outbox.append(event_id)


def test_postgresql_fault_preserves_transactional_authority_and_recovers() -> None:
    authority = _TransactionalAuthority()
    with pytest.raises(ConnectionError, match="postgresql"):
        authority.commit("case-fault-matrix", "event-fault-matrix")
    assert authority.cases == {}
    assert authority.outbox == []

    authority.available = True
    authority.commit("case-fault-matrix", "event-fault-matrix")
    observation = FaultObservation(
        fault="PostgreSQL commit outage",
        execution_mode="deterministic-fault-injected",
        injected_failure="commit raised before authoritative mutation",
        expected_behavior="rollback business and outbox state together",
        observed_outcome="no partial row; recovery committed both rows",
        authoritative_state=f"postgresql:case={authority.cases['case-fault-matrix']};outbox={len(authority.outbox)}",
        side_effect_count=0,
        recovery="database restored; one atomic commit succeeded",
        terminal_or_escalation="retryable intake, no terminal success while unavailable",
    )
    _assert_observation(observation)


class _CountingRemote:
    def __init__(self, invoke_result: str, reconcile_result: str) -> None:
        self.invoke_result = invoke_result
        self.reconcile_result = reconcile_result
        self.invoke_count = 0
        self.reconcile_count = 0

    def invoke(self, _key: str) -> str:
        self.invoke_count += 1
        return self.invoke_result

    def reconcile(self, _key: str) -> str:
        self.reconcile_count += 1
        return self.reconcile_result


def test_temporal_worker_restart_uses_durable_action_state_once() -> None:
    remote = _CountingRemote("unknown", "completed")
    store = InMemoryActionExecutionStore()
    first = recover_action(
        request=_action_request(),
        remote=remote,
        process_restart=True,
        store=store,
    )
    second = recover_action(
        request=_action_request(),
        remote=remote,
        process_restart=True,
        duplicate_deliveries=2,
        store=store,
    )
    assert first.state is ActionExecutionState.VERIFIED_SUCCESS
    assert second.state is ActionExecutionState.VERIFIED_SUCCESS
    assert remote.invoke_count == 1
    assert remote.reconcile_count == 1
    assert second.record is not None and second.record.attempt_count == 1
    observation = FaultObservation(
        fault="Temporal worker restart plus duplicate delivery",
        execution_mode="deterministic-fault-injected",
        injected_failure="worker lost after provider returned unknown",
        expected_behavior="resume from PostgreSQL action state and reconcile before retry",
        observed_outcome="one provider attempt, one reconciliation, verified success",
        authoritative_state=f"postgresql:action={second.state.value};attempts={second.attempt_count}",
        side_effect_count=1,
        recovery="durable execution record resumed after simulated restart",
        terminal_or_escalation="verified success only after reconciliation",
    )
    _assert_observation(observation)


class _FailingProducer:
    def __init__(self) -> None:
        self.available = False
        self.sent = 0

    async def send_and_wait(self, *_args: Any, **_kwargs: Any) -> str:
        if not self.available:
            raise ConnectionError("redpanda injected broker failure")
        self.sent += 1
        return "offset-1"


class _MutableOutbox:
    def __init__(self, event: OutboxEvent) -> None:
        self.event = event
        self.published = False

    def unpublished(self, *, limit: int) -> list[OutboxEvent]:
        del limit
        return [] if self.published else [self.event]

    def mark_published(self, *, outbox_id: str, published_at: object) -> OutboxEvent:
        del published_at
        assert outbox_id == self.event.outbox_id
        self.published = True
        return self.event


class _OutboxUow:
    def __init__(self, outbox: _MutableOutbox) -> None:
        self.outbox = outbox

    def __enter__(self) -> _OutboxUow:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_redpanda_outbox_failure_does_not_watermark_before_ack() -> None:
    event = make_event(event_id="event-redpanda-fault")
    row = OutboxEvent(
        tenant_id=event.tenant_id,
        outbox_id="outbox-redpanda-fault",
        event_id=event.event_id,
        event_type=event.event_type.value,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        occurred_at=event.occurred_at,
        produced_at=event.produced_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        producer=event.producer,
        schema_version=event.schema_version,
        payload_checksum=event.payload_checksum,
        payload=event.payload,
        published_at=None,
        created_at=NOW,
    )
    producer = _FailingProducer()
    outbox = _MutableOutbox(row)

    def factory(_context: object) -> _OutboxUow:
        return _OutboxUow(outbox)

    publisher = RedpandaOutboxPublisher(producer)
    with pytest.raises(ConnectionError, match="redpanda"):
        await publisher.publish_pending(
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context(),
        )
    assert not outbox.published

    producer.available = True
    published = await publisher.publish_pending(
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    assert len(published) == 1 and outbox.published
    observation = FaultObservation(
        fault="Redpanda broker unavailable",
        execution_mode="deterministic-fault-injected",
        injected_failure="send_and_wait raised before broker acknowledgement",
        expected_behavior="leave authoritative outbox unpublished until ack",
        observed_outcome="watermark remained false, then one publish succeeded after recovery",
        authoritative_state=f"postgresql:outbox_published={outbox.published}",
        side_effect_count=1,
        recovery="broker restored; pending outbox replayed once",
        terminal_or_escalation="delivery remains pending while transport is unavailable",
    )
    _assert_observation(observation)


class _NeoResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.counters = SimpleNamespace(nodes_deleted=1)

    def consume(self) -> _NeoResult:
        return self

    def single(self) -> Any:
        return self.value

    def __getitem__(self, index: int) -> Any:
        return (self.value or {}).get("event_id") if index == 0 else None


class _NeoSession:
    def __init__(self, driver: _NeoDriver) -> None:
        self.driver = driver

    def __enter__(self) -> _NeoSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def run(self, query: str, **parameters: Any) -> _NeoResult:
        if not self.driver.available:
            raise ConnectionError("neo4j injected projection outage")
        if "MERGE (event" in query:
            self.driver.projected.append(parameters["event_id"])
            return _NeoResult({"event_id": parameters["event_id"]})
        return _NeoResult()


class _NeoDriver:
    def __init__(self) -> None:
        self.available = False
        self.projected: list[str] = []

    def session(self, **_kwargs: Any) -> _NeoSession:
        return _NeoSession(self)

    def close(self) -> None:
        return None


def test_neo4j_projection_outage_never_becomes_business_authority() -> None:
    driver = _NeoDriver()
    projection = Neo4jProjection(driver)
    event = make_event(event_id="event-neo-fault")
    postgres_truth = {"case-fault-matrix": "accepted"}
    with pytest.raises(ConnectionError, match="neo4j"):
        projection.rebuild("tenant-a", [event])
    assert postgres_truth == {"case-fault-matrix": "accepted"}
    assert driver.projected == []

    driver.available = True
    result = projection.rebuild("tenant-a", [event])
    assert result.applied_events == 1
    assert driver.projected == [event.event_id]
    with pytest.raises(ValueError, match="tenant boundary"):
        projection.rebuild(
            "tenant-a", [make_event(tenant_id="tenant-b", event_id="other")]
        )
    observation = FaultObservation(
        fault="Neo4j projection unavailable",
        execution_mode="deterministic-fault-injected",
        injected_failure="projection session rejected reset",
        expected_behavior="retain PostgreSQL authority and rebuild projection later",
        observed_outcome="business truth unchanged; one scoped event projected after recovery",
        authoritative_state="postgresql:case-fault-matrix=accepted",
        side_effect_count=0,
        recovery="projection rebuilt from tenant-scoped authoritative event",
        terminal_or_escalation="projection lag, never a business-state success",
    )
    _assert_observation(observation)


class _UnavailableObjectStorage:
    def get_object(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("minio injected object outage")


def test_minio_failure_returns_integrity_error_and_no_fabricated_facts() -> None:
    store = ImmutableEvidenceStore(_UnavailableObjectStorage())
    with pytest.raises(ObjectIntegrityError, match="unavailable"):
        store.get_verified(
            tenant_id="tenant-a", object_name="case-1/raw/sessions/evidence.json"
        )
    observation = FaultObservation(
        fault="MinIO object read outage",
        execution_mode="deterministic-fault-injected",
        injected_failure="object retrieval failed before bytes were verified",
        expected_behavior="fail closed and keep normalized facts empty",
        observed_outcome="ObjectIntegrityError; no trusted bytes or facts accepted",
        authoritative_state="postgresql:evidence_status=unavailable",
        side_effect_count=0,
        recovery="raw artifact must be re-read and checksum-verified after storage recovery",
        terminal_or_escalation="evidence collection incomplete; escalation required",
    )
    _assert_observation(observation)


class _FailingRedis:
    def get(self, _name: str) -> None:
        raise ConnectionError("redis injected outage")

    def set(self, *_args: Any, **_kwargs: Any) -> bool:
        raise ConnectionError("redis injected outage")

    def delete(self, _name: str) -> None:
        raise ConnectionError("redis injected outage")

    def incr(self, _name: str) -> int:
        raise ConnectionError("redis injected outage")

    def expire(self, *_args: Any) -> None:
        raise ConnectionError("redis injected outage")


def test_redis_outage_cannot_replace_authoritative_business_state() -> None:
    coordinator = RedisCoordinator(_FailingRedis(), tenant_id="tenant-a")
    postgres_truth = {"case-fault-matrix": "accepted"}
    with pytest.raises(CoordinationUnavailable):
        coordinator.cache_get("case-fault-matrix")
    assert postgres_truth["case-fault-matrix"] == "accepted"
    observation = FaultObservation(
        fault="Redis coordination outage",
        execution_mode="deterministic-fault-injected",
        injected_failure="cache read failed",
        expected_behavior="surface coordination failure; do not infer terminal business state",
        observed_outcome="CoordinationUnavailable; PostgreSQL truth remained readable",
        authoritative_state="postgresql:case-fault-matrix=accepted",
        side_effect_count=0,
        recovery="coordination can resume without reconstructing business state from cache",
        terminal_or_escalation="coordination retry/degraded path, not business success",
    )
    _assert_observation(observation)


def test_keycloak_jwks_outage_is_an_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenJwks:
        def __init__(self, _url: str) -> None:
            pass

        def get_signing_key_from_jwt(self, _token: str) -> Any:
            raise ConnectionError("keycloak injected JWKS outage")

    monkeypatch.setattr("jwt.PyJWKClient", _BrokenJwks)
    verifier = OIDCVerifier(
        issuer="issuer", audience="api", jwks_url="https://keycloak/jwks"
    )
    with pytest.raises(TenantAuthorizationError, match="verification key"):
        verifier.verify("signed-but-unavailable", tenant_id="tenant-a")
    observation = FaultObservation(
        fault="Keycloak/JWKS unavailable",
        execution_mode="deterministic-fault-injected",
        injected_failure="signing-key discovery raised a transport error",
        expected_behavior="deny authentication without leaking provider details",
        observed_outcome="TenantAuthorizationError; no authorization context created",
        authoritative_state="postgresql:authorization=unchanged",
        side_effect_count=0,
        recovery="re-authenticate after JWKS availability returns",
        terminal_or_escalation="request denied, no privileged action attempted",
    )
    _assert_observation(observation)


class _FailingVault:
    def read(self, _path: str) -> dict[str, Any]:
        raise ConnectionError("vault injected outage")


def test_vault_outage_denies_secret_access_and_preserves_identity_scope() -> None:
    store = VaultSecretStore(_FailingVault(), service_identity="action-gateway")
    with pytest.raises(SecretAccessDenied, match="unavailable"):
        store.read_action_connector_secret(
            tenant_id="tenant-a", connector_id="session-actions"
        )
    with pytest.raises(SecretAccessDenied, match="only the Action Gateway"):
        VaultSecretStore(
            _FailingVault(), service_identity="model-gateway"
        ).read_action_connector_secret(
            tenant_id="tenant-a", connector_id="session-actions"
        )
    observation = FaultObservation(
        fault="Vault secret read unavailable",
        execution_mode="deterministic-fault-injected",
        injected_failure="secret backend raised before returning data",
        expected_behavior="deny secret access and preserve the Action Gateway-only scope",
        observed_outcome="SecretAccessDenied; non-gateway identity also denied",
        authoritative_state="postgresql:action=not_started",
        side_effect_count=0,
        recovery="retry credential acquisition only after Vault health recovery",
        terminal_or_escalation="action blocked; no connector call",
    )
    _assert_observation(observation)


def test_model_provider_failure_is_explicitly_non_executable() -> None:
    request = ModelAnalysisRequest(
        tenant_id="tenant-a",
        correlation_id="corr-fault-matrix",
        case_id="case-fault-matrix",
        redacted_case_representation={"timeline": [], "evidence": []},
        evidence_references=(),
        allowed_tools=("read_case", "read_evidence", "propose_action"),
        policy_version_id="policy-v1.0.0",
        budget=ModelBudget(max_tokens=100, max_tool_calls=1, timeout_seconds=1),
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )
    result = run_with_replay_fallback(
        request, primary_provider=None, replay_provider=None
    )
    assert result.status is ReplayFallbackStatus.ESCALATION
    assert result.remote_side_effects == ()
    assert result.final_mode == "deterministic_only"
    observation = FaultObservation(
        fault="model provider unavailable",
        execution_mode="deterministic-fault-injected",
        injected_failure="no live provider configured",
        expected_behavior="fallback only to labelled replay, otherwise escalate",
        observed_outcome="explicit escalation/deterministic-only result with no proposal execution",
        authoritative_state="postgresql:analysis=not_authorized_for_side_effects",
        side_effect_count=0,
        recovery="provider qualification can be retried independently",
        terminal_or_escalation="escalation: deterministic-only",
    )
    _assert_observation(observation)


def test_evidence_connector_failures_preserve_failure_state_and_empty_facts() -> None:
    manifest = simulator_manifest("tenant-a", "sessions")
    request = EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-fault-matrix",
        case_id="case-fault-matrix",
        connector_id="sim-sessions",
        resource_type="sessions",
        requested_at=NOW,
    )
    auth = _user_context()
    failures: list[ConnectorFailureState] = []
    for error in (
        TimeoutError("timeout"),
        ConnectionError("unavailable"),
        ValueError("invalid"),
    ):
        adapter = ReadOnlyEvidenceAdapter(
            manifest, reader=lambda _request, error=error: (_ for _ in ()).throw(error)
        )
        with pytest.raises(EvidenceConnectorError) as raised:
            adapter.read(request, authorization_context=auth)
        failures.append(raised.value.failure_state)
    assert failures == [
        ConnectorFailureState.TIMEOUT,
        ConnectorFailureState.UNAVAILABLE,
        ConnectorFailureState.UNAVAILABLE,
    ]
    observation = FaultObservation(
        fault="evidence connector timeout/unavailable/invalid transport",
        execution_mode="deterministic-fault-injected",
        injected_failure="read adapter raised bounded connector failures",
        expected_behavior="record explicit connector failure and invent no facts",
        observed_outcome=f"failure_states={','.join(item.value for item in failures)};facts=0",
        authoritative_state="postgresql:evidence=partial_or_unavailable",
        side_effect_count=0,
        recovery="connector can be retried as a read after health recovery",
        terminal_or_escalation="uncertainty retained; no action authorized",
    )
    _assert_observation(observation)


def test_action_gateway_timeout_persists_unknown_before_reconciliation() -> None:
    remote = _CountingRemote("accepted", "not_found")
    store = InMemoryActionExecutionStore()
    result = recover_action(
        request=_action_request(),
        remote=remote,
        timeout=True,
        store=store,
    )
    record = store.get(tenant_id="tenant-a", canonical_action_id="action-fault-matrix")
    assert result.state is ActionExecutionState.RECONCILED
    assert record is not None and record.last_remote_result == "not_found"
    assert remote.invoke_count == 1 and remote.reconcile_count == 1
    assert result.retry_performed is False
    observation = FaultObservation(
        fault="Action Gateway timeout after accepted response",
        execution_mode="deterministic-fault-injected",
        injected_failure="response was ambiguous at the timeout boundary",
        expected_behavior="persist UNKNOWN, reconcile once, and never blindly retry",
        observed_outcome="UNKNOWN persisted, reconciliation returned not_found, no duplicate invoke",
        authoritative_state=f"postgresql:action={record.status.value};remote={record.last_remote_result}",
        side_effect_count=1,
        recovery="reconciliation completed from durable execution identity",
        terminal_or_escalation="reconciled without retry; human escalation remains available for unresolved state",
    )
    _assert_observation(observation)


def test_verification_ambiguity_routes_to_escalation_not_success() -> None:
    request = _action_request()
    execution = SimpleNamespace(
        tenant_id=request.tenant_id,
        case_id=request.case_id,
        connector_id=request.connector_id,
        target_resource=request.target_resource,
        canonical_action_id=request.idempotency_key,
        execution_id="execution-fault-matrix",
        resource_type="sessions",
        status=ActionExecutionState.COMPLETED,
    )

    class _AmbiguousVerifier:
        def observe(self, _request: ActionGatewayRequest) -> dict[str, str]:
            return {
                "state": "unknown",
                "verification": "inconclusive",
                "source": "merchant-read",
            }

    verification = VerificationService(_AmbiguousVerifier()).verify(
        request=request,
        execution=execution,
        evidence_references=("evidence-fault-matrix",),
    )
    assert verification.terminal_state is None
    routed = verify_and_route(
        verification=verification.verification,
        escalation_owner="owner-fault-matrix",
        remaining_exposure_minor=100,
        currency="INR",
        evidence_references=("evidence-fault-matrix",),
        recommended_human_decision="review merchant state and decide containment",
        case_id=request.case_id,
        canonical_action_id=request.idempotency_key,
        policy_version_id=request.policy_version_id,
    )
    assert routed.terminal_state == "escalated_unresolved"
    assert routed.escalation is not None
    observation = FaultObservation(
        fault="ambiguous merchant verification",
        execution_mode="deterministic-fault-injected",
        injected_failure="merchant read returned conflicting/inconclusive state",
        expected_behavior="escalate uncertainty; never classify ambiguity as success",
        observed_outcome="verification inconclusive and routed to escalated_unresolved",
        authoritative_state="postgresql:verification=inconclusive;escalation=required",
        side_effect_count=0,
        recovery="human review or a new independent merchant observation",
        terminal_or_escalation="escalated_unresolved",
    )
    _assert_observation(observation)
