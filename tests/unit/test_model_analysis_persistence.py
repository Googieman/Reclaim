"""T076 persistence-boundary tests for typed, validated model analysis."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from analysis.proposal_validator import (
    AuthoritativeAttribution,
    AuthoritativeResource,
    ProposalValidationContext,
    ProposalValidator,
)
from analysis.deterministic_summary import DeterministicAnalysisResult
from app.audit.chain import AuditChain
from app.audit.model_analysis import ModelAnalysisAudit, ModelAnalysisPersistenceError
from app.db.repositories.model_runs import ModelRunRepository
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.db.tenant_context import TenantContext
from finance.exposure import FinancialExposure
from packages.contracts.analysis_policy import (
    ActionType,
    AttributionLabel,
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.common import CONTRACT_VERSION
from packages.contracts.connectors import (
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)
from agent.output_parser import TenantBoundAnalysisResponse


TENANT_ID = "tenant-t076"
CASE_ID = "case-t076"
CORRELATION_ID = "correlation-t076"
ANALYSIS_ID = "analysis-t076"
TIMELINE_ID = "timeline-t076"
EVIDENCE_ID = "evidence-t076"
RESOURCE_ID = "fulfillment-t076"
CONNECTOR_ID = "action-connector-t076"


def _request() -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        redacted_case_representation={
            "timeline": [
                {
                    "timeline_event_id": TIMELINE_ID,
                    "evidence_references": [EVIDENCE_ID],
                }
            ]
        },
        evidence_references=(EVIDENCE_ID,),
        policy_version_id="policy-t076",
        budget=ModelBudget(max_tokens=128),
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )


def _proposal() -> TypedActionProposal:
    return TypedActionProposal(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        analysis_id=ANALYSIS_ID,
        proposal_id="proposal-t076",
        action_type=ActionType.HOLD_FULFILLMENT,
        target_resource=RESOURCE_ID,
        parameters={"review_reason": "deterministic review"},
        rationale="Authoritative malicious activity requires bounded review.",
        evidence_references=(EVIDENCE_ID,),
        attribution_references=(TIMELINE_ID,),
        idempotency_key="proposal-t076-key",
    )


def _result() -> DeterministicAnalysisResult:
    request = _request()
    suggestion = {
        "timeline_event_id": TIMELINE_ID,
        "label": AttributionLabel.MALICIOUS,
        "confidence": 0.95,
        "rationale": "Deterministic fixture attribution.",
        "evidence_references": (EVIDENCE_ID,),
        "method": "rules",
        "model_or_rules_version": "rules-v1.0.0",
    }
    from packages.contracts.analysis_policy import AttributionSuggestion

    typed_attribution = AttributionSuggestion(**suggestion)
    response = TenantBoundAnalysisResponse(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        analysis_id=ANALYSIS_ID,
        provider="replay-fixture",
        model="deterministic-fixture",
        attributions=(typed_attribution,),
        proposals=(_proposal(),),
        uncertainty="review remains bounded",
        refusal_records=("untrusted instruction refused",),
    )
    exposure = FinancialExposure(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        currency="INR",
        gross_exposure_minor=10_000,
        recoverable_value_minor=8_000,
        contained_value_minor=3_000,
        legitimate_value_disrupted_minor=250,
        irreversible_loss_minor=2_000,
        remaining_exposure_minor=5_000,
        calculation_version="exposure-v1.0.0",
        source_references=(TIMELINE_ID,),
        uncertain_source_references=(),
        payment_references=("payment-t076",),
    )
    return DeterministicAnalysisResult(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        mode="replay",
        deterministic_seed="seed-t076",
        attributions=(typed_attribution,),
        exposure=exposure,
        uncertainty=("review remains bounded",),
        attribution_labels={TIMELINE_ID: AttributionLabel.MALICIOUS.value},
        proposal_inputs=(),
        policy_inputs={"policy_version_id": "policy-t076"},
        outcome_record={
            "analysis_version": "deterministic-analysis-v1.0.0",
            "input_references": (EVIDENCE_ID, TIMELINE_ID),
        },
        feature_schema_version=None,
        model_versions=("rules-v1.0.0",),
        metadata={"analysis_output_references": ("raw-output-t076",)},
        analysis_request=request,
        analysis_response=response,
    )


def _connector() -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        connector_id=CONNECTOR_ID,
        contract_version=CONTRACT_VERSION,
        connector_type=ConnectorType.ACTION,
        mode=ConnectorMode.SIMULATOR,
        resources=("fulfillment",),
        operations=(ActionType.HOLD_FULFILLMENT.value,),
        auth_scope=(f"{TENANT_ID}:action:t076",),
        request_schema="ActionConnectorRequest",
        response_schema="ActionConnectorResponse",
        timestamp_semantics="utc",
        idempotency_behavior="stable action identity",
        failure_states=("invalid", "unknown_result"),
    )


def _validated_result() -> tuple[DeterministicAnalysisResult, object]:
    result = _result()
    context = ProposalValidationContext.from_analysis_result(
        result,
        connectors={CONNECTOR_ID: _connector()},
        action_connector_ids={ActionType.HOLD_FULFILLMENT.value: CONNECTOR_ID},
        resources={
            RESOURCE_ID: AuthoritativeResource(
                resource_id=RESOURCE_ID,
                resource_type="fulfillment",
                tenant_id=TENANT_ID,
                case_id=CASE_ID,
                state="created",
                connector_id=CONNECTOR_ID,
                evidence_references=(EVIDENCE_ID,),
                timeline_event_ids=(TIMELINE_ID,),
            )
        },
        evidence_references=(EVIDENCE_ID,),
        timeline_events=(
            {
                "timeline_event_id": TIMELINE_ID,
                "tenant_id": TENANT_ID,
                "case_id": CASE_ID,
                "evidence_references": (EVIDENCE_ID,),
                "event_payload": {"fulfillment_id": RESOURCE_ID},
            },
        ),
        attributions=(
            AuthoritativeAttribution(
                timeline_event_id=TIMELINE_ID,
                label=AttributionLabel.MALICIOUS,
                confidence=0.95,
                tenant_id=TENANT_ID,
                case_id=CASE_ID,
                evidence_references=(EVIDENCE_ID,),
                rationale="Deterministic fixture attribution.",
                method="rules",
                model_or_rules_version="rules-v1.0.0",
            ),
        ),
    )
    return result, ProposalValidator().validate(
        result.analysis_response.proposals[0], context
    )


def _audit() -> ModelAnalysisAudit:
    result, validation = _validated_result()
    return ModelAnalysisAudit.from_result(
        result,
        proposal_validations={"proposal-t076": validation},
        created_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )


class _Cursor:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    def fetchone(self) -> object | None:
        return self.row

    def fetchall(self) -> list[object]:
        return []


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: Any = ()) -> _Cursor:
        values = tuple(params) if params else ()
        self.calls.append((query, values))
        if "INSERT INTO public.model_runs" in query:
            return _Cursor(
                (TENANT_ID, ANALYSIS_ID, CASE_ID, "replay", "checksum", "checksum")
            )
        if "INSERT INTO public.model_run_proposals" in query:
            return _Cursor((TENANT_ID, ANALYSIS_ID, "proposal-t076", "valid"))
        return _Cursor()


class _AuditRepository:
    def __init__(self) -> None:
        self.records: list[object] = []

    def lock_chain(self, *, tenant_id: str) -> None:
        assert tenant_id == TENANT_ID

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        assert tenant_id == TENANT_ID
        return self.records[-1].record_checksum if self.records else None

    def checksum_for_audit_id(self, *, tenant_id: str, audit_id: str) -> str | None:
        del tenant_id, audit_id
        return None

    def append(self, record: object) -> object:
        self.records.append(record)
        return record


def _tenant_context() -> TenantContext:
    authorization = TenantAuthorizationContext(
        subject="service-t076",
        tenant_id=TENANT_ID,
        roles=frozenset({"reviewer"}),
        identity_type=IdentityType.SERVICE,
        issuer="https://issuer.test",
    )
    return TenantContext.from_authorization_context(authorization)


def test_t076_requires_typed_t075_validation_and_keeps_proposals_non_executable() -> (
    None
):
    result = _result()
    with pytest.raises(ModelAnalysisPersistenceError, match="validation result"):
        ModelAnalysisAudit.from_result(result)

    audit = _audit()
    assert audit.validated is True
    assert audit.deterministic_seed == "seed-t076"
    assert audit.proposals[0].validation_status == "valid"
    assert audit.proposals[0].policy_evaluation_ready is True
    assert audit.proposals[0].execution_state == "not_executable"
    assert audit.proposals[0].approval_state == "not_approved"
    assert audit.refusal_records == ("untrusted instruction refused",)
    assert audit.as_dict()["deterministic_seed"] == "seed-t076"


def test_t076_uses_append_only_audit_chain_and_tenant_bound_repository() -> None:
    audit = _audit()
    audit_repository = _AuditRepository()
    audit_chain = AuditChain(audit_repository)
    record = audit.append_audit_record(audit_chain, audit_id="audit-t076")
    assert record.action == "model.analysis.persisted"
    assert record.case_id == CASE_ID
    assert record.record_checksum != "pending"
    assert audit_repository.records == [record]

    connection = _RecordingConnection()
    repository = ModelRunRepository(connection, _tenant_context())
    row = repository.persist(audit)
    assert row[1] == ANALYSIS_ID
    assert len([query for query, _ in connection.calls if "model_runs" in query]) == 1
    assert (
        len([query for query, _ in connection.calls if "model_run_proposals" in query])
        == 1
    )
    model_run_params = next(
        params
        for query, params in connection.calls
        if "INSERT INTO public.model_runs" in query
    )
    assert model_run_params[4] == "seed-t076"
    assert (
        "action_gateway" not in " ".join(query for query, _ in connection.calls).lower()
    )

    with pytest.raises(Exception, match="tenant"):
        repository.persist(replace(audit, tenant_id="tenant-other"))


def test_t076_rejects_stale_response_checksum_before_persistence() -> None:
    result = _result()
    stale = replace(result, metadata={"analysis_response_checksum": "0" * 64})
    _, validation = _validated_result()
    with pytest.raises(ModelAnalysisPersistenceError, match="checksum"):
        ModelAnalysisAudit.from_result(
            stale,
            proposal_validations={"proposal-t076": validation},
        )
