"""T078 US2 integration gate from canonical evidence to advisory persistence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from acceptance.test_attribution_exposure_analysis import _prepared_case, _run
from analysis.deterministic_summary import run_us2_analysis
from analysis.proposal_validator import (
    AuthoritativeResource,
    ProposalValidationContext,
    ProposalValidationStatus,
    ProposalValidator,
)
from app.db.repositories.model_runs import ModelRunRepository
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.db.tenant_context import TenantContext
from agent.providers import ReplayProvider
from agent.replay_fallback import ReplayFallbackStatus, run_with_replay_fallback
from packages.contracts.analysis_policy import (
    ActionType,
    ModelAnalysisResponse,
    ProviderMode,
)
from packages.contracts.common import CONTRACT_VERSION
from packages.contracts.connectors import (
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)
from agent.output_parser import TenantBoundAnalysisResponse


pytestmark = pytest.mark.integration


class _Cursor:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    def fetchone(self) -> object | None:
        return self.row

    def fetchall(self) -> list[object]:
        return []


class _RecordingPostgresConnection:
    """A transaction-shaped recorder for the repository contract gate."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: Any = ()) -> _Cursor:
        values = tuple(params) if params else ()
        self.calls.append((query, values))
        if "INSERT INTO public.model_runs" in query:
            return _Cursor(
                (values[0], values[1], values[2], values[5], values[14], values[15])
            )
        if "INSERT INTO public.model_run_proposals" in query:
            return _Cursor((values[0], values[1], values[3], values[5]))
        return _Cursor()


def _authorization_context(tenant_id: str) -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject="service-t078",
        tenant_id=tenant_id,
        roles=frozenset({"reviewer"}),
        identity_type=IdentityType.SERVICE,
        issuer="https://issuer.test",
    )


def _action_connector(tenant_id: str, correlation_id: str) -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        connector_id="action-connector-t078",
        contract_version=CONTRACT_VERSION,
        connector_type=ConnectorType.ACTION,
        mode=ConnectorMode.SIMULATOR,
        resources=("sessions", "fulfillment", "orders", "payments", "profile_changes"),
        operations=tuple(action.value for action in ActionType),
        auth_scope=(f"{tenant_id}:action:t078",),
        request_schema="ActionConnectorRequest",
        response_schema="ActionConnectorResponse",
        timestamp_semantics="utc",
        idempotency_behavior="stable action identity",
        failure_states=("invalid", "unknown_result"),
    )


def _timeline_snapshot(timeline: Any) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "timeline_event_id": event.timeline_event_id,
            "tenant_id": event.tenant_id,
            "case_id": event.case_id,
            "evidence_references": event.evidence_references,
            "event_payload": event.event_payload,
        }
        for event in timeline.events
    )


def _validation_context(
    result: Any, evidence: Any, timeline: Any
) -> ProposalValidationContext:
    proposal = result.analysis_response.proposals[0]
    target_event = next(
        event
        for event in timeline.events
        if event.timeline_event_id == proposal.target_resource
    )
    # The canonical replay fixture intentionally proposes a fulfillment hold against a
    # profile-change timeline identity.  The authoritative resource snapshot therefore
    # makes T075 reject it before any policy/execution path can see it.
    resource = AuthoritativeResource(
        resource_id=proposal.target_resource,
        resource_type="profile_changes",
        tenant_id=result.tenant_id,
        case_id=result.case_id,
        state="created",
        connector_id="action-connector-t078",
        evidence_references=target_event.evidence_references,
        timeline_event_ids=(target_event.timeline_event_id,),
    )
    return ProposalValidationContext.from_analysis_result(
        result,
        connectors={
            "action-connector-t078": _action_connector(
                result.tenant_id, result.correlation_id
            )
        },
        action_connector_ids={
            ActionType.HOLD_FULFILLMENT.value: "action-connector-t078",
        },
        resources={resource.resource_id: resource},
        evidence_references=tuple(item.evidence_id for item in evidence.items),
        timeline_events=_timeline_snapshot(timeline),
        attributions=result.attribution_inputs,
    )


def test_t078_canonical_us2_analysis_exposure_gate_is_validated_and_non_executable() -> (
    None
):
    evidence, timeline = _prepared_case()
    result = _run(run_us2_analysis, evidence, timeline)
    replayed = _run(run_us2_analysis, evidence, timeline, reverse=True)

    assert result.analysis_request is not None
    assert result.analysis_request.provider_mode is ProviderMode.REPLAY
    assert result.analysis_request.replay_label is ProviderMode.REPLAY
    assert result.analysis_response is not None
    assert isinstance(result.analysis_response, TenantBoundAnalysisResponse)
    assert isinstance(result.analysis_response, ModelAnalysisResponse)
    assert result.analysis_response.case_id == result.case_id
    assert result.exposure.gross_exposure_minor == 129_900
    assert result.exposure.recoverable_value_minor == 100_000
    assert result.exposure.remaining_exposure_minor == 30_000
    assert result.uncertainty
    assert result.remote_side_effects == ()
    assert result.analysis_request.redacted_case_representation
    assert "action_gateway" not in result.analysis_request.allowed_tools

    assert result.analysis_response.model_dump(
        mode="json"
    ) == replayed.analysis_response.model_dump(mode="json")
    assert (
        result.outcome_record["record_checksum"]
        == replayed.outcome_record["record_checksum"]
    )

    live_request = result.analysis_request.model_copy(
        update={"provider_mode": ProviderMode.LIVE, "replay_label": ProviderMode.LIVE}
    )
    fallback = run_with_replay_fallback(
        live_request,
        primary_provider=None,
        replay_provider=ReplayProvider(
            provider=result.analysis_response.provider,
            model=result.analysis_response.model,
            response=result.analysis_response.model_dump(
                mode="json", exclude_none=True
            ),
        ),
        deterministic_uncertainty=result.uncertainty,
    )
    assert fallback.status is ReplayFallbackStatus.REPLAY
    assert (
        fallback.effective_request.redacted_case_representation
        == live_request.redacted_case_representation
    )
    assert fallback.analysis_response is not None
    assert fallback.analysis_response.model_dump(
        mode="json"
    ) == result.analysis_response.model_dump(mode="json")

    context = _validation_context(result, evidence, timeline)
    proposal = result.analysis_response.proposals[0]
    validation = ProposalValidator().validate(proposal, context)
    assert validation.status is ProposalValidationStatus.REJECTED
    assert any("incompatible" in reason for reason in validation.reasons)
    assert validation.policy_evaluation_ready is False
    assert validation.remote_side_effects == ()

    from app.audit.model_analysis import ModelAnalysisAudit

    audit = ModelAnalysisAudit.from_result(
        result,
        proposal_validations={proposal.proposal_id: validation},
    )
    assert audit.mode == "replay"
    assert audit.replay_label == "replay"
    assert audit.deterministic_exposure_checksum
    assert audit.proposals[0].validation_status == "rejected"
    assert audit.proposals[0].execution_state == "not_executable"
    assert audit.proposals[0].approval_state == "not_approved"
    assert audit.proposals[0].proposal.action_type.value == "hold_fulfillment"
    assert audit.provenance["authoritative_store"] == "postgresql"
    assert audit.provenance["side_effects"] is False

    connection = _RecordingPostgresConnection()
    repository = ModelRunRepository(
        connection,
        TenantContext.from_authorization_context(
            _authorization_context(result.tenant_id)
        ),
    )
    stored = repository.persist(audit)
    assert stored[0] == result.tenant_id
    assert stored[1] == result.analysis_response.analysis_id
    assert any(
        "INSERT INTO public.model_runs" in query for query, _ in connection.calls
    )
    assert any(
        "INSERT INTO public.model_run_proposals" in query
        for query, _ in connection.calls
    )
    assert not any("action_gateway" in query.lower() for query, _ in connection.calls)


def test_t078_model_analysis_migration_declares_public_authority_and_rls() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "db"
        / "migrations"
        / "007_model_analysis_runs.sql"
    ).read_text(encoding="utf-8")
    for fragment in (
        "CREATE TABLE IF NOT EXISTS public.model_runs",
        "CREATE TABLE IF NOT EXISTS public.model_run_proposals",
        "ALTER TABLE public.model_runs FORCE ROW LEVEL SECURITY",
        "ALTER TABLE public.model_run_proposals FORCE ROW LEVEL SECURITY",
        "reclaim.require_tenant_context()",
        "CHECK (mode = replay_label)",
        "CHECK (irreversible_loss_minor = gross_exposure_minor - recoverable_value_minor)",
        "CHECK (remaining_exposure_minor = recoverable_value_minor - contained_value_minor)",
        "CHECK (execution_state = 'not_executable')",
        "CHECK (approval_state = 'not_approved')",
    ):
        assert fragment in migration


def test_action_idempotency_schema_keeps_concurrent_retries_on_one_key() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "db"
        / "migrations"
        / "001_authoritative_entities.sql"
    ).read_text(encoding="utf-8")

    action_proposals = migration[
        migration.index("CREATE TABLE IF NOT EXISTS action_proposals") :
    ]
    assert "UNIQUE (tenant_id, idempotency_key)" in action_proposals
    assert "CREATE TABLE IF NOT EXISTS action_executions" in action_proposals
    assert action_proposals.count("UNIQUE (tenant_id, idempotency_key)") >= 2


def test_t076_fresh_model_analysis_migration_is_search_path_safe() -> None:
    database_url = os.getenv("RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL is required for fresh migration validation"
        )

    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(database_url)
    migration_root = (
        Path(__file__).resolve().parents[2] / "backend" / "db" / "migrations"
    )
    try:
        connection.execute("BEGIN")
        connection.execute("SET LOCAL search_path TO public")
        for migration_name in (
            "001_authoritative_entities.sql",
            "002_tenant_isolation.sql",
            "003_batch_b_integrity.sql",
            "004_final_gate_integrity.sql",
            "007_model_analysis_runs.sql",
        ):
            connection.execute(
                (migration_root / migration_name).read_text(encoding="utf-8")
            )

        assert connection.execute(
            "SELECT to_regclass('public.model_runs') IS NOT NULL"
        ).fetchone() == (True,)
        assert connection.execute(
            "SELECT to_regclass('public.model_run_proposals') IS NOT NULL"
        ).fetchone() == (True,)
        policy_rows = connection.execute(
            """
            SELECT tablename, policyname
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename IN ('model_runs', 'model_run_proposals')
            ORDER BY tablename, policyname
            """
        ).fetchall()
        assert policy_rows == [
            ("model_run_proposals", "model_run_proposals_tenant_isolation"),
            ("model_runs", "model_runs_tenant_isolation"),
        ]
    finally:
        connection.rollback()
        connection.close()


def test_t076_non_owner_model_analysis_rls_requires_tenant_context() -> None:
    database_url = os.getenv("RECLAIM_MODEL_ANALYSIS_RLS_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "RECLAIM_MODEL_ANALYSIS_RLS_DATABASE_URL is required for non-owner RLS validation"
        )

    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(database_url)
    try:
        connection.execute("BEGIN")
        connection.execute("SET LOCAL search_path TO public")
        with pytest.raises(psycopg.Error, match="tenant context"):
            connection.execute("SELECT count(*) FROM public.model_runs")
    finally:
        connection.rollback()
        connection.close()
