"""US2 deterministic attribution, exposure, and advisory hand-off.

Deterministic attribution and exposure remain authoritative.  T074 adds only the
bounded model-response hand-off after those values are calculated; it does not
authorize policy, persistence, or a connector/action-gateway call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from agent.providers import ModelProvider, ReplayProvider
from agent.redaction import build_analysis_request
from agent.replay_fallback import run_with_replay_fallback
from attribution.lightgbm_adapter import LightGBMBaselineAdapter
from attribution.models import AttributionRecord, attribution_input_from_event
from attribution.rules import RulesAttributor
from finance.exposure import FinancialExposure, calculate_exposure
from packages.contracts.analysis_policy import (
    AttributionLabel,
    AttributionSuggestion,
    ModelAnalysisRequest,
    ModelAnalysisResponse,
    ProviderMode,
)

DETERMINISTIC_ANALYSIS_VERSION = "deterministic-analysis-v1.0.0"
EXPOSURE_VERSION = "exposure-v1.0.0"


@dataclass(frozen=True, slots=True)
class DeterministicAnalysisResult:
    """Replayable output of the deterministic attribution/exposure stage."""

    tenant_id: str
    case_id: str
    correlation_id: str
    mode: str
    deterministic_seed: str
    attributions: tuple[AttributionSuggestion, ...]
    exposure: FinancialExposure
    uncertainty: tuple[str, ...]
    attribution_labels: Mapping[str, str]
    proposal_inputs: tuple[Mapping[str, Any], ...]
    policy_inputs: Mapping[str, Any]
    outcome_record: Mapping[str, Any]
    attribution_inputs: tuple[AttributionRecord, ...] = ()
    feature_schema_version: str | None = None
    model_versions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    analysis_request: ModelAnalysisRequest | None = None
    analysis_response: ModelAnalysisResponse | None = None
    forbidden_attempts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("tenant_id", "case_id", "correlation_id", "mode", "deterministic_seed"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"deterministic analysis {name} is required")
        object.__setattr__(self, "attributions", tuple(self.attributions))
        object.__setattr__(self, "uncertainty", tuple(sorted(set(self.uncertainty))))
        object.__setattr__(
            self, "proposal_inputs", tuple(dict(item) for item in self.proposal_inputs)
        )
        object.__setattr__(self, "policy_inputs", dict(self.policy_inputs))
        object.__setattr__(self, "attribution_labels", dict(self.attribution_labels))
        object.__setattr__(self, "outcome_record", dict(self.outcome_record))
        object.__setattr__(self, "attribution_inputs", tuple(self.attribution_inputs))
        object.__setattr__(self, "model_versions", tuple(sorted(set(self.model_versions))))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "forbidden_attempts", tuple(self.forbidden_attempts))
        if self.analysis_request is not None:
            if (
                self.analysis_request.tenant_id != self.tenant_id
                or self.analysis_request.case_id != self.case_id
                or self.analysis_request.correlation_id != self.correlation_id
            ):
                raise ValueError("analysis request does not match deterministic result scope")

    @property
    def labels(self) -> Mapping[str, str]:
        return self.attribution_labels

    @property
    def review_or_escalation(self) -> bool:
        return bool(self.policy_inputs.get("review_or_escalation", False))

    @property
    def remote_side_effects(self) -> tuple[object, ...]:
        """The deterministic/model-analysis stages expose no side-effect channel."""

        return ()


def propagate_uncertainty(
    *,
    tenant_id: str,
    case_id: str,
    timeline_events: Iterable[object],
    attributions: Iterable[object],
    missing_evidence_event_ids: Iterable[str] = (),
    timeline_uncertainty: Iterable[str] = (),
) -> dict[str, Any]:
    """Carry timeline uncertainty into all deterministic analysis inputs.

    A missing attribution, provenance mismatch, conflicting source, or explicit
    uncertain label is represented as uncertainty.  No missing result is replaced by
    a malicious or legitimate guess.
    """

    events = _validated_events(timeline_events, tenant_id=tenant_id, case_id=case_id)
    missing_evidence_ids = set(
        _references(missing_evidence_event_ids, "missing_evidence_event_ids")
    )
    external_uncertainty = _references(timeline_uncertainty, "timeline_uncertainty")
    suggestions_by_event: dict[str, list[AttributionSuggestion]] = {}
    for value in attributions:
        suggestion, record_identity = _coerce_suggestion(value)
        if record_identity is not None and (
            record_identity[0] != tenant_id or record_identity[1] != case_id
        ):
            raise ValueError("attribution crosses tenant or case boundary")
        if suggestion.timeline_event_id not in events:
            raise ValueError("attribution references an event outside the authoritative timeline")
        event = events[suggestion.timeline_event_id]
        if not set(suggestion.evidence_references).issubset(set(event.evidence_references)):
            # A result that cannot be linked to the authoritative event is not trusted.
            continue
        suggestions_by_event.setdefault(suggestion.timeline_event_id, []).append(suggestion)

    labels: dict[str, str] = {}
    confidence: dict[str, float] = {}
    rationales: dict[str, str] = {}
    unknown_event_ids: list[str] = []
    uncertainty: set[str] = set()
    proposal_inputs: list[dict[str, Any]] = []
    malicious_event_ids: list[str] = []
    legitimate_event_ids: list[str] = []
    uncertain_event_ids: list[str] = []

    for event_id in sorted(events):
        event = events[event_id]
        suggestions = suggestions_by_event.get(event_id, [])
        event_uncertainty = set(event.uncertainty_reasons)
        if event_id in missing_evidence_ids:
            event_uncertainty.add("missing_evidence")
        if event.conflicting_source_event_ids:
            event_uncertainty.add("conflicting_sources")
        for marker in external_uncertainty:
            prefix = f"{event.dedupe_key}:"
            if marker == event.dedupe_key:
                event_uncertainty.add("timeline_uncertainty")
            elif marker.startswith(prefix):
                event_uncertainty.add(marker.removeprefix(prefix))
        if not suggestions:
            unknown_event_ids.append(event_id)
            event_uncertainty.add("missing_attribution")
        suggestion_labels = {suggestion.label for suggestion in suggestions}
        if AttributionLabel.UNCERTAIN in suggestion_labels:
            event_uncertainty.add("uncertain_attribution")
        if (
            AttributionLabel.MALICIOUS in suggestion_labels
            and AttributionLabel.LEGITIMATE in suggestion_labels
        ):
            event_uncertainty.add("conflicting_attributions")

        if event_uncertainty:
            label = AttributionLabel.UNCERTAIN.value
            selected_confidence = min(
                (suggestion.confidence for suggestion in suggestions), default=0.0
            )
            rationale = _uncertain_rationale(event_uncertainty)
            for reason in sorted(event_uncertainty):
                uncertainty.add(f"{event.dedupe_key}:{reason}")
        else:
            label = _consensus_label(suggestion_labels).value
            selected_confidence = min(suggestion.confidence for suggestion in suggestions)
            rationale = _representative_rationale(suggestions, label)

        labels[event_id] = label
        confidence[event_id] = selected_confidence
        rationales[event_id] = rationale
        if label == AttributionLabel.MALICIOUS.value:
            malicious_event_ids.append(event_id)
        elif label == AttributionLabel.LEGITIMATE.value:
            legitimate_event_ids.append(event_id)
        else:
            uncertain_event_ids.append(event_id)
        proposal_inputs.append(
            {
                "timeline_event_id": event_id,
                "label": label,
                "confidence": selected_confidence,
                "rationale": rationale,
                "evidence_references": event.evidence_references,
                "attribution_references": tuple(
                    sorted({suggestion.timeline_event_id for suggestion in suggestions})
                ),
            }
        )

    review_or_escalation = bool(uncertain_event_ids)
    policy_inputs = {
        "attribution_labels": dict(labels),
        "confidence_by_event": dict(confidence),
        "malicious_event_ids": malicious_event_ids,
        "legitimate_event_ids": legitimate_event_ids,
        "uncertain_event_ids": uncertain_event_ids,
        "review_or_escalation": review_or_escalation,
        "uncertainty_preserved": review_or_escalation,
    }
    return {
        "labels": labels,
        "attribution_labels": labels,
        "confidence_by_event": confidence,
        "rationales": rationales,
        "unknown_event_ids": unknown_event_ids,
        "uncertainty": tuple(sorted(uncertainty)),
        "proposal_inputs": tuple(proposal_inputs),
        "policy_inputs": policy_inputs,
        "review_or_escalation": review_or_escalation,
    }


def aggregate_attributions(
    *,
    tenant_id: str,
    case_id: str,
    timeline_events: Iterable[object],
    attributions: Iterable[object],
) -> dict[str, Any]:
    """Aggregate advisory methods without allowing one method to hide conflict."""

    return propagate_uncertainty(
        tenant_id=tenant_id,
        case_id=case_id,
        timeline_events=timeline_events,
        attributions=attributions,
    )


def run_us2_analysis(
    *,
    tenant_id: str,
    case_id: str,
    correlation_id: str,
    evidence_items: Iterable[object],
    timeline_events: Iterable[object],
    timeline_uncertainty: Iterable[str] = (),
    policy_version_id: str = "policy-v1.0.0",
    provider_mode: ProviderMode | str = ProviderMode.REPLAY,
    deterministic_seed: str | int = "0",
    lightgbm_adapter: LightGBMBaselineAdapter | None = None,
    model_provider: ModelProvider | None = None,
    replay_provider: ModelProvider | None = None,
) -> DeterministicAnalysisResult:
    """Run deterministic analysis, then parse one bounded advisory response.

    A replay provider is used when no provider is supplied for the existing
    replay-oriented canonical path.  A live provider failure is handled by the
    T077 deterministic replay boundary; deterministic attribution and exposure
    are returned even when both model paths fail.
    """

    _required_text(tenant_id, "tenant_id")
    _required_text(case_id, "case_id")
    _required_text(correlation_id, "correlation_id")
    _required_text(policy_version_id, "policy_version_id")
    mode = provider_mode.value if isinstance(provider_mode, ProviderMode) else str(provider_mode)
    if mode not in {ProviderMode.LIVE.value, ProviderMode.REPLAY.value}:
        raise ValueError("provider mode is unsupported")
    seed = str(deterministic_seed)
    _required_text(seed, "deterministic_seed")

    evidence = tuple(evidence_items)
    input_events = tuple(timeline_events)
    event_by_id = _validated_events(input_events, tenant_id=tenant_id, case_id=case_id)
    events = tuple(event_by_id[event_id] for event_id in sorted(event_by_id))
    evidence_ids = _validated_evidence(evidence, tenant_id=tenant_id, case_id=case_id)
    missing_evidence_event_ids = {
        event.timeline_event_id for event in events if set(event.evidence_references) - evidence_ids
    }

    rules = RulesAttributor()
    model = lightgbm_adapter or LightGBMBaselineAdapter.default()
    suggestions: list[AttributionSuggestion] = []
    records: list[AttributionRecord] = []
    model_versions: set[str] = set()
    for event in sorted(events, key=_event_sort_key):
        input_value = attribution_input_from_event(event)
        rules_suggestion = rules.attribute(input_value, tenant_id=tenant_id, case_id=case_id)
        suggestions.append(rules_suggestion)
        records.append(AttributionRecord(input_value, rules_suggestion))
        if _is_payment_event(event):
            feature_vector = _feature_vector(event)
            if feature_vector is not None:
                try:
                    model_suggestion = model.predict(
                        tenant_id=tenant_id,
                        case_id=case_id,
                        timeline_event_id=event.timeline_event_id,
                        feature_vector=feature_vector,
                        evidence_references=event.evidence_references,
                    )
                except ValueError:
                    model_suggestion = None
                if model_suggestion is not None:
                    suggestions.append(model_suggestion)
                    records.append(AttributionRecord(input_value, model_suggestion))
                    model_versions.add(model_suggestion.model_or_rules_version)

    propagated = propagate_uncertainty(
        tenant_id=tenant_id,
        case_id=case_id,
        timeline_events=events,
        attributions=records,
        missing_evidence_event_ids=missing_evidence_event_ids,
        timeline_uncertainty=timeline_uncertainty,
    )
    uncertainty = set(propagated["uncertainty"])
    uncertainty.update(_references(timeline_uncertainty, "timeline_uncertainty"))
    for event_id in sorted(missing_evidence_event_ids):
        uncertainty.add(f"{event_by_id[event_id].dedupe_key}:missing_evidence")

    payments = _payment_inputs(
        events,
        labels=propagated["labels"],
        evidence_ids=evidence_ids,
    )
    calculation_currency = _currency_from_payments(payments)
    exposure = calculate_exposure(
        tenant_id=tenant_id,
        case_id=case_id,
        payments=tuple(payments),
        calculation_version=EXPOSURE_VERSION,
        currency=calculation_currency,
    )
    input_references = _input_references(evidence, events)
    output_references = tuple(
        sorted(
            {
                f"attribution:{suggestion.timeline_event_id}:{suggestion.method}"
                for suggestion in suggestions
            }
            | {f"exposure:{tenant_id}:{case_id}:{EXPOSURE_VERSION}"}
        )
    )
    record_without_checksum = {
        "tenant_id": tenant_id,
        "case_id": case_id,
        "correlation_id": correlation_id,
        "mode": mode,
        "deterministic_seed": seed,
        "policy_version_id": policy_version_id,
        "analysis_version": DETERMINISTIC_ANALYSIS_VERSION,
        "input_references": input_references,
        "output_references": output_references,
        "attribution_versions": tuple(
            sorted({suggestion.model_or_rules_version for suggestion in suggestions})
        ),
        "feature_schema_version": model.feature_schema_version,
        "exposure_version": exposure.calculation_version,
        "uncertainty": tuple(sorted(uncertainty)),
    }
    record_checksum = _checksum(record_without_checksum)
    outcome_record = {
        **record_without_checksum,
        "record_checksum": record_checksum,
        "replay_live_mode": mode,
    }
    result = DeterministicAnalysisResult(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=correlation_id,
        mode=mode,
        deterministic_seed=seed,
        attributions=tuple(suggestions),
        exposure=exposure,
        uncertainty=tuple(sorted(uncertainty)),
        attribution_labels=propagated["labels"],
        proposal_inputs=propagated["proposal_inputs"],
        policy_inputs={
            **propagated["policy_inputs"],
            "policy_version_id": policy_version_id,
        },
        outcome_record=outcome_record,
        attribution_inputs=tuple(records),
        feature_schema_version=model.feature_schema_version,
        model_versions=tuple(sorted(model_versions | {"rules-v1.0.0"})),
        metadata={"authoritative_store": "postgresql", "side_effects": False},
    )
    analysis_request = build_analysis_request(
        result,
        evidence_items=evidence,
        timeline_events=events,
    )
    default_replay = ReplayProvider(
        response_factory=lambda request, _tool_results: _default_replay_response(request, result)
    )
    if mode == ProviderMode.REPLAY.value:
        selected_replay = replay_provider or model_provider or default_replay
        selected_primary = None
    else:
        selected_replay = replay_provider or default_replay
        selected_primary = model_provider
    fallback = run_with_replay_fallback(
        analysis_request,
        primary_provider=selected_primary,
        replay_provider=selected_replay,
        deterministic_uncertainty=result.uncertainty,
    )
    fallback_metadata = {
        **result.metadata,
        "analysis_status": fallback.status.value,
        "analysis_requested_mode": mode,
        "analysis_mode": fallback.mode,
        "analysis_replay_label": fallback.label,
        "analysis_fallback_version": fallback.provenance.get("fallback_version"),
        "analysis_fallback_reason": fallback.fallback_reason,
        "analysis_primary_failure": fallback.primary_failure,
        "analysis_failure_kind": fallback.failure_kind,
        "analysis_request_checksum": fallback.provenance.get("request_checksum"),
        "analysis_side_effects": False,
    }
    if fallback.parsed_response is None:
        return replace(
            result,
            analysis_request=fallback.effective_request,
            metadata=fallback_metadata,
            forbidden_attempts=tuple(
                sorted(set(result.forbidden_attempts) | set(fallback.forbidden_attempts))
            ),
        )
    parsed = fallback.parsed_response
    return replace(
        result,
        analysis_request=fallback.effective_request,
        analysis_response=parsed.response,
        forbidden_attempts=tuple(
            sorted(
                set(result.forbidden_attempts)
                | set(fallback.forbidden_attempts)
                | set(parsed.response.refusal_records)
            )
        ),
        metadata={
            **fallback_metadata,
            "analysis_provider": parsed.provenance.provider,
            "analysis_model": parsed.provenance.model,
            "analysis_parser_version": parsed.provenance.parser_version,
            "analysis_response_checksum": parsed.provenance.response_checksum,
            "analysis_token_count": parsed.provenance.token_count,
            "analysis_estimated_cost": parsed.provenance.estimated_cost,
            "analysis_provenance": fallback.provenance,
        },
    )


def _validated_events(values: Iterable[object], *, tenant_id: str, case_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        event = attribution_input_from_event(value)
        if event.tenant_id != tenant_id or event.case_id != case_id:
            raise ValueError("timeline event crosses tenant or case boundary")
        if event.timeline_event_id in result and result[event.timeline_event_id] != value:
            raise ValueError("timeline event identity has conflicting values")
        result[event.timeline_event_id] = value
    return result


def _validated_evidence(values: Sequence[object], *, tenant_id: str, case_id: str) -> set[str]:
    identifiers: set[str] = set()
    for value in values:
        value_tenant = getattr(value, "tenant_id", None)
        value_case = getattr(value, "case_id", None)
        evidence_id = getattr(value, "evidence_id", None)
        if isinstance(value, Mapping):
            value_tenant = value.get("tenant_id")
            value_case = value.get("case_id")
            evidence_id = value.get("evidence_id")
        if value_tenant != tenant_id or value_case != case_id:
            raise ValueError("evidence crosses tenant or case boundary")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("evidence_id is required")
        identifiers.add(evidence_id)
    return identifiers


def _coerce_suggestion(
    value: object,
) -> tuple[AttributionSuggestion, tuple[str, str] | None]:
    if isinstance(value, AttributionRecord):
        return value.suggestion, (value.tenant_id, value.case_id)
    if isinstance(value, AttributionSuggestion):
        return value, None
    if isinstance(value, Mapping):
        return AttributionSuggestion.model_validate(value), None
    raise TypeError("attribution must be an AttributionSuggestion or AttributionRecord")


def _consensus_label(labels: set[AttributionLabel]) -> AttributionLabel:
    if not labels:
        return AttributionLabel.UNCERTAIN
    if len(labels) != 1:
        return AttributionLabel.UNCERTAIN
    return next(iter(labels))


def _representative_rationale(suggestions: Sequence[AttributionSuggestion], label: str) -> str:
    matching = [suggestion for suggestion in suggestions if suggestion.label.value == label]
    return max(
        matching, key=lambda suggestion: (suggestion.confidence, suggestion.method)
    ).rationale


def _uncertain_rationale(reasons: set[str]) -> str:
    joined_reasons = ", ".join(sorted(reasons))
    return (
        f"Deterministic attribution remains uncertain ({joined_reasons}); "
        "human review is required."
    )


def _event_sort_key(event: object) -> tuple[object, ...]:
    effective_at = getattr(event, "effective_at", datetime.min)
    return (
        effective_at,
        str(getattr(event, "ordering_key", "")),
        str(getattr(event, "timeline_event_id", "")),
    )


def _is_payment_event(event: object) -> bool:
    event_type = str(getattr(event, "canonical_event_type", ""))
    return event_type.startswith("payment.")


def _feature_vector(event: object) -> dict[str, Any] | None:
    payload = getattr(event, "event_payload", {})
    if not isinstance(payload, Mapping):
        return None
    required = (
        "payment_amount_minor",
        "new_device",
        "profile_change_24h",
        "session_velocity_5m",
        "successful_customer_orders",
    )
    if "payment_amount_minor" not in payload and "amount_minor" in payload:
        payload = {**payload, "payment_amount_minor": payload["amount_minor"]}
    if any(name not in payload for name in required):
        return None
    return {name: payload[name] for name in required}


def _payment_inputs(
    events: Sequence[object], *, labels: Mapping[str, str], evidence_ids: set[str]
) -> list[dict[str, Any]]:
    payments: list[dict[str, Any]] = []
    for event in sorted(events, key=_event_sort_key):
        if not _is_payment_event(event):
            continue
        payload = getattr(event, "event_payload", {})
        if not isinstance(payload, Mapping):
            continue
        amount = payload.get("amount_minor")
        payment_id = payload.get("payment_id")
        currency = payload.get("currency")
        source = payload.get("payment_source")
        if not all(
            isinstance(value, str) and value.strip() for value in (payment_id, currency, source)
        ):
            continue
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        payments.append(
            {
                "tenant_id": event.tenant_id,
                "case_id": event.case_id,
                "payment_id": payment_id,
                "timeline_event_id": event.timeline_event_id,
                "evidence_references": tuple(
                    reference
                    for reference in event.evidence_references
                    if reference in evidence_ids
                ),
                "amount_minor": amount,
                "currency": currency,
                "payment_source": source,
                "state": payload.get("state", payload.get("payment_state")),
                "reimbursed_minor": payload.get("reimbursed_minor", 0),
                "contained_minor": payload.get("contained_minor", 0),
                "attribution_label": labels.get(
                    event.timeline_event_id, AttributionLabel.UNCERTAIN.value
                ),
                "legitimate_value_disrupted_minor": payload.get(
                    "legitimate_value_disrupted_minor", 0
                ),
            }
        )
    return payments


def _currency_from_payments(payments: Sequence[Mapping[str, Any]]) -> str | None:
    currencies = {value.get("currency") for value in payments if value.get("currency")}
    if len(currencies) == 1:
        return str(next(iter(currencies)))
    return None


def _input_references(evidence: Sequence[object], events: Sequence[object]) -> tuple[str, ...]:
    references: set[str] = set()
    for item in evidence:
        evidence_id = getattr(item, "evidence_id", None)
        if isinstance(item, Mapping):
            evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str):
            references.add(evidence_id)
    for event in events:
        references.add(event.timeline_event_id)
        references.update(event.evidence_references)
        references.update(event.source_event_ids)
    return tuple(sorted(references))


def _references(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise ValueError(f"{name} must be a sequence")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{name} contains an invalid reference")
    return tuple(sorted(set(item.strip() for item in values)))


def _checksum(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _default_replay_response(
    request: ModelAnalysisRequest, result: DeterministicAnalysisResult
) -> dict[str, Any]:
    """Create the deterministic replay fixture consumed by the T074 parser.

    This is a provider fixture, not a model decision.  It deliberately emits no
    financial fields and only proposes a bounded review action using references
    already present in the request.  A real provider can be supplied through the
    provider-neutral ``model_provider`` argument.
    """

    analysis_id = f"analysis-{result.case_id}-{result.deterministic_seed}"
    proposal_inputs = tuple(
        value
        for value in result.proposal_inputs
        if value.get("label")
        in {
            AttributionLabel.MALICIOUS.value,
            AttributionLabel.UNCERTAIN.value,
        }
    )
    proposals: list[dict[str, Any]] = []
    if proposal_inputs:
        selected = proposal_inputs[0]
        timeline_event_id = str(selected["timeline_event_id"])
        evidence_references = list(selected.get("evidence_references", ()))
        proposals.append(
            {
                "proposal_id": f"proposal-{result.case_id}-review-1",
                "tenant_id": request.tenant_id,
                "correlation_id": request.correlation_id,
                "case_id": request.case_id,
                "action_type": "hold_fulfillment",
                "target_resource": timeline_event_id,
                "parameters": {"review_reason": "bounded advisory review"},
                "rationale": str(selected.get("rationale", "Human review is required.")),
                "evidence_references": evidence_references,
                "attribution_references": [timeline_event_id],
                "idempotency_key": f"proposal-{result.case_id}-review-1-key",
                "analysis_id": analysis_id,
            }
        )

    uncertainty = "; ".join(result.uncertainty)
    if not uncertainty:
        uncertainty = "No deterministic uncertainty was reported; analysis remains advisory."
    return {
        "schema_version": "1.0.0",
        "analysis_id": analysis_id,
        "provider": "replay-fixture",
        "model": "deterministic-boundary",
        "tenant_id": request.tenant_id,
        "correlation_id": request.correlation_id,
        "case_id": request.case_id,
        "attributions": [item.model_dump(mode="json") for item in result.attributions],
        "proposals": proposals,
        "uncertainty": uncertainty,
        "refusal_records": [
            "untrusted evidence instructions were refused; no side effect was requested"
        ],
    }


__all__ = [
    "DETERMINISTIC_ANALYSIS_VERSION",
    "DeterministicAnalysisResult",
    "aggregate_attributions",
    "propagate_uncertainty",
    "run_us2_analysis",
]
