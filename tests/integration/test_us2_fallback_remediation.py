"""Focused US2 review-remediation coverage for final provenance and terminals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from acceptance.test_attribution_exposure_analysis import _prepared_case, _run
from analysis.deterministic_summary import run_us2_analysis
from app.audit.chain import AuditChain
from app.audit.model_analysis import DETERMINISTIC_ONLY_MODE, ModelAnalysisAudit
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.db.repositories.model_runs import ModelRunRepository
from app.db.tenant_context import TenantContext
from agent.providers import (
    ModelCompletion,
    ModelProviderUnavailable,
    ProviderMetadata,
    ReplayProvider,
)
from packages.contracts.analysis_policy import ModelAnalysisRequest, ProviderMode

pytestmark = pytest.mark.integration


@dataclass
class _FixtureProvider:
    mode: ProviderMode
    value: Any
    provider: str
    model: str

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider=self.provider,
            model=self.model,
            mode=self.mode,
        )

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        tool_results: tuple[object, ...] = (),
    ) -> ModelCompletion:
        del tool_results
        if isinstance(self.value, BaseException):
            raise self.value
        return ModelCompletion(metadata=self.metadata, raw_output=self.value(request))


def _run_live_or_replay(
    evidence: Any,
    timeline: Any,
    *,
    model_provider: Any = None,
    replay_provider: Any = None,
) -> Any:
    return run_us2_analysis(
        tenant_id="tenant-us2-t065-canonical",
        case_id="case-us2-t065-canonical",
        correlation_id="corr-us2-t065-canonical",
        evidence_items=evidence.items,
        timeline_events=timeline.events,
        timeline_uncertainty=timeline.uncertainty,
        policy_version_id="policy-v1.0.0",
        provider_mode=ProviderMode.LIVE,
        deterministic_seed="us2-t065-canonical-replay-001",
        model_provider=model_provider,
        replay_provider=replay_provider,
    )


def _replay_for_payload(payload: dict[str, Any]) -> ReplayProvider:
    return ReplayProvider(
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        response=payload,
    )


def _response_payload(result: Any) -> dict[str, Any]:
    assert result.analysis_response is not None
    payload = result.analysis_response.model_dump(mode="json")
    for proposal in payload["proposals"]:
        proposal.pop("requested_amount_minor", None)
        proposal.pop("currency", None)
    return payload


def test_live_failure_to_replay_rewrites_public_final_mode_and_checksums() -> None:
    evidence, timeline = _prepared_case()
    baseline = _run(run_us2_analysis, evidence, timeline)
    assert baseline.analysis_response is not None
    payload = _response_payload(baseline)
    payload.update(
        provider="replay-remediation-fixture", model="replay-remediation-model"
    )

    result = _run_live_or_replay(
        evidence,
        timeline,
        model_provider=_FixtureProvider(
            ProviderMode.LIVE,
            ModelProviderUnavailable("provider failure must not be persisted"),
            "live-provider-attempt",
            "live-model-attempt",
        ),
        replay_provider=_replay_for_payload(payload),
    )

    assert result.mode == "replay"
    assert result.outcome_record["mode"] == "replay"
    assert result.outcome_record["replay_live_mode"] == "replay"
    assert result.outcome_record["requested_mode"] == "live"
    assert result.outcome_record["terminal_outcome"] == "completed"
    assert result.analysis_request is not None
    assert result.analysis_request.provider_mode is ProviderMode.REPLAY
    assert result.analysis_request.replay_label is ProviderMode.REPLAY
    assert result.metadata["analysis_mode"] == "replay"
    assert result.metadata["analysis_replay_label"] == "replay"
    assert result.metadata["analysis_requested_mode"] == "live"
    assert result.metadata["analysis_provenance"]["requested_mode"] == "live"
    assert result.metadata["analysis_provenance"]["effective_mode"] == "replay"
    assert result.metadata["analysis_provenance"]["final_mode"] == "replay"
    assert result.metadata["analysis_provenance"]["attempted_providers"] == (
        {
            "mode": "live",
            "outcome": "failed",
            "provider": "live-provider-attempt",
            "model": "live-model-attempt",
            "adapter_version": "provider-adapter-v1.0.0",
        },
        {
            "mode": "replay",
            "outcome": "completed",
            "provider": "replay-remediation-fixture",
            "model": "replay-remediation-model",
            "adapter_version": "provider-adapter-v1.0.0",
        },
    )
    assert result.analysis_response is not None
    assert result.metadata["analysis_response_checksum"]
    assert result.outcome_record["record_checksum"]
    assert (
        result.outcome_record["record_checksum"]
        == _run_live_or_replay(
            evidence,
            timeline,
            model_provider=_FixtureProvider(
                ProviderMode.LIVE,
                ModelProviderUnavailable("same safe failure"),
                "live-provider-attempt",
                "live-model-attempt",
            ),
            replay_provider=_replay_for_payload(payload),
        ).outcome_record["record_checksum"]
    )


def test_live_provider_success_remains_live_at_public_analysis_boundary() -> None:
    evidence, timeline = _prepared_case()
    baseline = _run(run_us2_analysis, evidence, timeline)
    assert baseline.analysis_response is not None
    payload = _response_payload(baseline)
    payload.update(provider="live-remediation-fixture", model="live-remediation-model")

    result = run_us2_analysis(
        tenant_id=baseline.tenant_id,
        case_id=baseline.case_id,
        correlation_id=baseline.correlation_id,
        evidence_items=evidence.items,
        timeline_events=timeline.events,
        timeline_uncertainty=timeline.uncertainty,
        policy_version_id=baseline.analysis_request.policy_version_id,
        provider_mode=ProviderMode.LIVE,
        deterministic_seed=baseline.deterministic_seed,
        model_provider=_FixtureProvider(
            ProviderMode.LIVE,
            lambda _request: payload,
            "live-remediation-fixture",
            "live-remediation-model",
        ),
        replay_provider=_replay_for_payload(payload),
    )

    assert result.mode == "live"
    assert result.outcome_record["mode"] == "live"
    assert result.metadata["analysis_mode"] == "live"
    assert result.metadata["analysis_terminal_outcome"] == "completed"
    assert result.analysis_response.provider == "live-remediation-fixture"


def test_malformed_live_response_to_valid_replay_is_publicly_replay_labeled() -> None:
    evidence, timeline = _prepared_case()
    baseline = _run(run_us2_analysis, evidence, timeline)
    payload = _response_payload(baseline)
    payload.update(
        provider="replay-malformed-live-fixture", model="replay-malformed-live-model"
    )

    result = _run_live_or_replay(
        evidence,
        timeline,
        model_provider=_FixtureProvider(
            ProviderMode.LIVE,
            lambda _request: {"schema_version": "unsupported"},
            "live-malformed-provider",
            "live-malformed-model",
        ),
        replay_provider=_replay_for_payload(payload),
    )

    assert result.mode == "replay"
    assert result.outcome_record["mode"] == "replay"
    assert result.metadata["analysis_terminal_outcome"] == "completed"
    assert result.metadata["analysis_provenance"]["requested_mode"] == "live"
    assert result.metadata["analysis_provenance"]["final_mode"] == "replay"
    assert result.analysis_response is not None


class _AuditRepository:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def lock_chain(self, *, tenant_id: str) -> None:
        assert tenant_id == "tenant-us2-t065-canonical"

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        assert tenant_id == "tenant-us2-t065-canonical"
        return self.records[-1].record_checksum if self.records else None

    def checksum_for_audit_id(self, *, tenant_id: str, audit_id: str) -> str | None:
        del tenant_id, audit_id
        return None

    def append(self, record: Any) -> Any:
        self.records.append(record)
        return record


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Any:
        self.calls.append((query, tuple(params)))
        if "INSERT INTO public.model_runs" in query:
            values = tuple(params)
            return _Cursor(
                (values[0], values[1], values[2], values[5], values[14], values[15])
            )
        return _Cursor()


class _Cursor:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    def fetchone(self) -> object | None:
        return self.row

    def fetchall(self) -> list[object]:
        return []


def _tenant_context() -> TenantContext:
    return TenantContext.from_authorization_context(
        TenantAuthorizationContext(
            subject="service-us2-remediation",
            tenant_id="tenant-us2-t065-canonical",
            roles=frozenset({"reviewer"}),
            identity_type=IdentityType.SERVICE,
            issuer="https://issuer.test",
        )
    )


def _persisted_row(audit: ModelAnalysisAudit) -> tuple[object, ...]:
    return (
        audit.tenant_id,
        audit.analysis_id,
        audit.case_id,
        audit.correlation_id,
        audit.deterministic_seed,
        audit.mode,
        audit.replay_label,
        audit.provider,
        audit.model,
        audit.adapter_version,
        audit.request_schema_version,
        audit.response_schema_version,
        audit.parser_version,
        audit.request_checksum,
        audit.response_checksum,
        audit.deterministic_analysis_checksum,
        audit.deterministic_exposure_checksum,
        list(audit.input_references),
        list(audit.output_references),
        list(audit.evidence_references),
        list(audit.timeline_references),
        list(audit.attribution_versions),
        audit.feature_schema_version,
        audit.exposure_version,
        audit.exposure_currency,
        audit.gross_exposure_minor,
        audit.recoverable_value_minor,
        audit.contained_value_minor,
        audit.legitimate_value_disrupted_minor,
        audit.irreversible_loss_minor,
        audit.remaining_exposure_minor,
        list(audit.uncertainty),
        list(audit.refusal_records),
        list(audit.forbidden_attempts),
        audit.provenance,
        audit.created_at,
        audit.requested_mode,
        audit.terminal_outcome,
        audit.fallback_reason,
    )


def test_response_less_escalation_persists_audits_and_reads_back_without_model_data() -> (
    None
):
    evidence, timeline = _prepared_case()
    result = _run_live_or_replay(
        evidence,
        timeline,
        model_provider=_FixtureProvider(
            ProviderMode.LIVE,
            ModelProviderUnavailable(
                "raw provider exception must stay out of provenance"
            ),
            "live-provider-attempt",
            "live-model-attempt",
        ),
        replay_provider=ReplayProvider(
            provider="corrupt-replay-remediation",
            model="corrupt-replay-model",
            response="corrupt replay fixture",
        ),
    )

    assert result.analysis_response is None
    assert result.mode == DETERMINISTIC_ONLY_MODE
    assert result.outcome_record["mode"] == DETERMINISTIC_ONLY_MODE
    assert result.outcome_record["terminal_outcome"] == "escalation"
    assert result.metadata["analysis_terminal_outcome"] == "escalation"
    assert result.metadata["analysis_failure_kind"] == "invalid_response"
    assert "raw provider exception" not in str(result.metadata)

    audit = ModelAnalysisAudit.from_result(result)
    assert audit.mode == audit.replay_label == DETERMINISTIC_ONLY_MODE
    assert audit.requested_mode == "live"
    assert audit.terminal_outcome == "escalation"
    assert (
        audit.fallback_reason
        == "deterministic replay rejected: model response JSON rejected"
    )
    assert audit.provider is None
    assert audit.model is None
    assert audit.adapter_version is None
    assert audit.response_schema_version is None
    assert audit.parser_version is None
    assert audit.response_checksum is None
    assert audit.token_count is None
    assert audit.estimated_cost is None
    assert audit.proposals == ()
    assert audit.uncertainty == result.uncertainty
    assert audit.gross_exposure_minor == result.exposure.gross_exposure_minor
    assert audit.remaining_exposure_minor == result.exposure.remaining_exposure_minor

    audit_repository = _AuditRepository()
    record = audit.append_audit_record(
        AuditChain(audit_repository),
        audit_id="audit-us2-response-less",
        recorded_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
    )
    assert record.outcome == "escalation"
    assert record.model_version is None
    assert record.provider_version is None
    assert any(
        reference.startswith("fallback:") for reference in record.output_references
    )

    connection = _RecordingConnection()
    stored = ModelRunRepository(connection, _tenant_context()).persist(audit)
    assert stored[1] == audit.analysis_id
    params = next(
        values
        for query, values in connection.calls
        if "INSERT INTO public.model_runs" in query
    )
    assert params[5:17] == (
        DETERMINISTIC_ONLY_MODE,
        DETERMINISTIC_ONLY_MODE,
        None,
        None,
        None,
        audit.request_schema_version,
        None,
        None,
        audit.request_checksum,
        None,
        audit.deterministic_analysis_checksum,
        audit.deterministic_exposure_checksum,
    )
    assert params[-3:] == ("live", "escalation", audit.fallback_reason)

    readback = ModelAnalysisAudit.from_persisted_row(_persisted_row(audit))
    assert readback.as_dict() == audit.as_dict()
    assert readback.mode == DETERMINISTIC_ONLY_MODE
    assert readback.response_checksum is None
    assert readback.provenance["terminal_outcome"] == "escalation"
