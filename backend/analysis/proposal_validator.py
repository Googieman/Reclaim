"""Deterministic, advisory validation of typed action proposals.

The model boundary (T074) proves that an output can be represented as a
``TypedActionProposal``.  This module is the next, independent safety gate: it
checks that the proposal is still inside the tenant/case/analysis scope and is
bounded by authoritative resource, attribution, exposure, and connector
declarations.  It deliberately has no persistence or execution dependency.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from finance.exposure import FinancialExposure
from packages.contracts.analysis_policy import (
    ActionType,
    AttributionLabel,
    ModelAnalysisRequest,
    ModelAnalysisResponse,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.common import CONTRACT_VERSION
from packages.contracts.connectors import ConnectorType

PROPOSAL_VALIDATOR_VERSION = "proposal-validator-v1.0.0"
ACTION_IDENTITY_VERSION = "action-identity-v1.0.0"


class ProposalValidationStatus(StrEnum):
    """Advisory outcomes; none of them authorizes policy or execution."""

    VALID = "valid"
    REJECTED = "rejected"
    ESCALATION_ONLY = "escalation_only"


ValidationStatus = ProposalValidationStatus


@dataclass(frozen=True, slots=True)
class AuthoritativeResource:
    """Read-only state for the exact merchant resource a proposal targets."""

    resource_id: str
    resource_type: str
    tenant_id: str
    case_id: str
    state: str
    connector_id: str | None = None
    evidence_references: tuple[str, ...] = ()
    timeline_event_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    version: str = "resource-v1.0.0"

    def __post_init__(self) -> None:
        for name in ("resource_id", "resource_type", "tenant_id", "case_id", "state", "version"):
            _required_text(getattr(self, name), f"resource {name}")
        if self.connector_id is not None:
            _required_text(self.connector_id, "resource connector_id")
        object.__setattr__(self, "evidence_references", _references(self.evidence_references))
        object.__setattr__(self, "timeline_event_ids", _references(self.timeline_event_ids))
        if not isinstance(self.attributes, Mapping):
            raise ValueError("resource attributes must be an object")
        object.__setattr__(self, "attributes", dict(self.attributes))


ResourceState = AuthoritativeResource


@dataclass(frozen=True, slots=True)
class AuthoritativeAttribution:
    """A deterministic attribution associated with one timeline event."""

    timeline_event_id: str
    label: AttributionLabel | str
    confidence: float
    tenant_id: str
    case_id: str
    evidence_references: tuple[str, ...] = ()
    rationale: str = ""
    method: str = ""
    model_or_rules_version: str = ""

    def __post_init__(self) -> None:
        for name in ("timeline_event_id", "tenant_id", "case_id"):
            _required_text(getattr(self, name), f"attribution {name}")
        try:
            label = (
                self.label.value
                if isinstance(self.label, AttributionLabel)
                else AttributionLabel(self.label)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("attribution label is unsupported") from exc
        object.__setattr__(self, "label", label)
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, int | float):
            raise ValueError("attribution confidence must be numeric")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("attribution confidence must be between 0 and 1")
        object.__setattr__(self, "evidence_references", _references(self.evidence_references))


AttributionState = AuthoritativeAttribution


@dataclass(frozen=True, slots=True)
class ProposalValidationContext:
    """Immutable authoritative inputs consumed by :class:`ProposalValidator`.

    ``connectors`` contains declarations/manifests only.  It must not contain a
    client, credential, callback, or gateway.  ``resources``, ``timeline_events``,
    and ``attributions`` are snapshots read through approved services/repositories;
    this class never fetches them itself.
    """

    tenant_id: str
    case_id: str
    correlation_id: str
    analysis_id: str
    evidence_references: frozenset[str] = frozenset()
    evidence_items: Sequence[object] = ()
    timeline_events: Mapping[str, object] | Sequence[object] = field(default_factory=dict)
    attributions: Mapping[str, object] | Sequence[object] = field(default_factory=dict)
    resources: Mapping[str, object] | Sequence[object] = field(default_factory=dict)
    ambiguous_resource_ids: frozenset[str] = frozenset()
    connectors: Mapping[str, object] | object = field(default_factory=dict)
    action_connector_ids: Mapping[str, str] = field(default_factory=dict)
    connector_registry: object | None = None
    exposure: FinancialExposure | Mapping[str, Any] | None = None
    analysis_request: ModelAnalysisRequest | None = None
    analysis_response: ModelAnalysisResponse | None = None
    analysis_provenance: Mapping[str, Any] = field(default_factory=dict)
    uncertainty_references: frozenset[str] = frozenset()
    input_versions: Mapping[str, str] = field(default_factory=dict)
    authoritative_versions: Mapping[str, str] = field(default_factory=dict)
    analysis_input_version: str | None = None
    authoritative_analysis_input_version: str | None = None
    response_checksum: str | None = None
    provider: str | None = None
    model: str | None = None
    provider_mode: ProviderMode | str | None = None
    replay_label: ProviderMode | str | None = None
    existing_idempotency_keys: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "case_id", "correlation_id", "analysis_id"):
            _required_text(getattr(self, name), f"validation context {name}")
        object.__setattr__(
            self, "evidence_references", frozenset(_references(self.evidence_references))
        )
        object.__setattr__(
            self, "uncertainty_references", frozenset(_references(self.uncertainty_references))
        )
        object.__setattr__(self, "evidence_items", tuple(self.evidence_items))
        object.__setattr__(
            self, "timeline_events", _index_values(self.timeline_events, "timeline_event_id")
        )
        object.__setattr__(
            self, "attributions", _index_values(self.attributions, "timeline_event_id")
        )
        normalized_resources, discovered_ambiguities = _index_resources(self.resources)
        object.__setattr__(self, "resources", normalized_resources)
        object.__setattr__(
            self,
            "ambiguous_resource_ids",
            frozenset((*_references(self.ambiguous_resource_ids), *discovered_ambiguities)),
        )
        connector_source = self.connectors
        if isinstance(connector_source, Mapping):
            normalized_connectors = dict(connector_source)
        else:
            normalized_connectors = {}
            if self.connector_registry is None:
                object.__setattr__(self, "connector_registry", connector_source)
        object.__setattr__(self, "connectors", normalized_connectors)
        object.__setattr__(self, "action_connector_ids", dict(self.action_connector_ids))
        object.__setattr__(self, "analysis_provenance", dict(self.analysis_provenance))
        object.__setattr__(self, "input_versions", dict(self.input_versions))
        object.__setattr__(self, "authoritative_versions", dict(self.authoritative_versions))
        object.__setattr__(self, "existing_idempotency_keys", dict(self.existing_idempotency_keys))

    @classmethod
    def from_analysis_result(
        cls,
        result: object,
        *,
        connectors: Mapping[str, object],
        resources: Mapping[str, object] | Sequence[object],
        evidence_references: Iterable[str] = (),
        timeline_events: Mapping[str, object] | Sequence[object] = (),
        attributions: Mapping[str, object] | Sequence[object] = (),
        **overrides: Any,
    ) -> ProposalValidationContext:
        """Build a context from the existing deterministic US2 result object."""

        response = getattr(result, "analysis_response", None)
        analysis_id = getattr(response, "analysis_id", None)
        if not isinstance(analysis_id, str) or not analysis_id.strip():
            raise ValueError("analysis result does not contain a typed analysis identity")
        return cls(
            tenant_id=str(result.tenant_id),
            case_id=str(result.case_id),
            correlation_id=str(result.correlation_id),
            analysis_id=analysis_id,
            evidence_references=frozenset(evidence_references),
            timeline_events=timeline_events,
            attributions=attributions or getattr(result, "attribution_inputs", ()),
            resources=resources,
            connectors=connectors,
            exposure=getattr(result, "exposure", None),
            analysis_request=getattr(result, "analysis_request", None),
            analysis_response=response,
            uncertainty_references=frozenset(getattr(result, "uncertainty", ())),
            provider=getattr(response, "provider", None),
            model=getattr(response, "model", None),
            provider_mode=getattr(getattr(result, "analysis_request", None), "provider_mode", None),
            replay_label=getattr(getattr(result, "analysis_request", None), "replay_label", None),
            **overrides,
        )


AuthoritativeProposalState = ProposalValidationContext


@dataclass(frozen=True, slots=True)
class ProposalValidationResult:
    """Replayable advisory validation output; it contains no execution handle."""

    status: ProposalValidationStatus
    proposal_id: str | None
    tenant_id: str | None
    case_id: str | None
    analysis_id: str | None
    action_type: str | None
    connector_id: str | None
    reasons: tuple[str, ...]
    evidence_references: tuple[str, ...]
    attribution_references: tuple[str, ...]
    validation_version: str
    authoritative_input_checksum: str
    proposal_checksum: str
    validation_checksum: str
    replay_live_mode: str | None
    provider: str | None
    model: str | None
    policy_evaluation_ready: bool
    audit_record: Mapping[str, Any]
    canonical_action_identity: str | None = None

    @property
    def valid(self) -> bool:
        return self.status is ProposalValidationStatus.VALID

    @property
    def escalation_only(self) -> bool:
        return self.status is ProposalValidationStatus.ESCALATION_ONLY

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        return self.reasons

    @property
    def remote_side_effects(self) -> tuple[object, ...]:
        return ()

    @property
    def canonical_idempotency_key(self) -> str | None:
        """The trusted action key; any proposal-supplied key is advisory only."""

        return self.canonical_action_identity

    @property
    def action_idempotency_key(self) -> str | None:
        """Compatibility alias for the trusted canonical action key."""

        return self.canonical_action_identity

    def __getitem__(self, name: str) -> Any:
        return getattr(self, name)


class ProposalValidator:
    """Perform deterministic pre-policy checks on one typed proposal."""

    def __init__(self, *, validation_version: str = PROPOSAL_VALIDATOR_VERSION) -> None:
        self.validation_version = _required_text(validation_version, "validation_version")

    def validate(
        self,
        proposal: object,
        context: ProposalValidationContext | Mapping[str, Any] | None = None,
        *,
        state: ProposalValidationContext | Mapping[str, Any] | None = None,
        authoritative_state: ProposalValidationContext | Mapping[str, Any] | None = None,
        **context_values: Any,
    ) -> ProposalValidationResult:
        """Return a deterministic result without calling a remote or write API."""

        bound_context = context or state or authoritative_state
        if bound_context is None and context_values:
            bound_context = ProposalValidationContext(**context_values)
        if isinstance(bound_context, Mapping):
            try:
                bound_context = ProposalValidationContext(**bound_context)
            except (TypeError, ValueError) as exc:
                return self._malformed_result(proposal, f"invalid validation context: {exc}")
        if not isinstance(bound_context, ProposalValidationContext):
            return self._malformed_result(proposal, "authoritative validation context is required")

        return self._validate(proposal, bound_context)

    check = validate

    def _validate(
        self, proposal: object, context: ProposalValidationContext
    ) -> ProposalValidationResult:
        hard: list[str] = []
        escalation: list[str] = []
        action: ActionType | None = None
        connector_id: str | None = None
        canonical_action_identity: str | None = None
        proposal_values = _proposal_values(proposal, hard)
        proposal_checksum = _checksum(proposal_values)

        if not isinstance(proposal, TypedActionProposal):
            hard.append("proposal must be a TypedActionProposal")
        else:
            _check_direct_model_shape(proposal, hard)

        if proposal_values:
            _check_contract_identity(proposal_values, context, hard)
            action = _action_type(proposal_values.get("action_type"), hard)
            _check_parameters(proposal_values.get("parameters"), action, hard)
            _check_rationale(proposal_values.get("rationale"), hard)
            proposal_evidence = _reference_values(
                proposal_values.get("evidence_references"), "proposal evidence references", hard
            )
            proposal_attributions = _reference_values(
                proposal_values.get("attribution_references"),
                "proposal attribution references",
                hard,
            )
            _check_money(proposal_values, action, context, hard)
        else:
            proposal_evidence = ()
            proposal_attributions = ()

        _check_analysis_binding(proposal_values, context, hard)
        _check_versions_and_mode(context, hard)

        if action is not None:
            connector_id = self._resolve_connector(action, context, hard)
            resource = self._resolve_resource(
                proposal_values.get("target_resource"),
                action,
                connector_id,
                context,
                hard,
            )
            canonical_action_identity = _canonical_action_idempotency_key(
                proposal_values,
                action=action,
                connector_id=connector_id,
                resource=resource,
                validation_version=self.validation_version,
            )
            _check_idempotency(
                proposal_values,
                canonical_action_identity,
                context,
                hard,
            )
            self._check_references(
                proposal_evidence,
                proposal_attributions,
                resource,
                context,
                hard,
                escalation,
            )
            self._check_action_preconditions(
                action,
                proposal_values,
                resource,
                context,
                hard,
                escalation,
            )

        status = (
            ProposalValidationStatus.REJECTED
            if hard
            else ProposalValidationStatus.ESCALATION_ONLY
            if escalation
            else ProposalValidationStatus.VALID
        )
        reasons = _stable_reasons((*hard, *escalation))
        authoritative_checksum = _authoritative_checksum(context)
        validation_checksum = _checksum(
            {
                "validation_version": self.validation_version,
                "proposal_checksum": proposal_checksum,
                "canonical_action_identity": canonical_action_identity,
                "authoritative_input_checksum": authoritative_checksum,
                "status": status.value,
                "reasons": reasons,
            }
        )
        result = ProposalValidationResult(
            status=status,
            proposal_id=_optional_text(proposal_values.get("proposal_id")),
            tenant_id=_optional_text(proposal_values.get("tenant_id")),
            case_id=_optional_text(proposal_values.get("case_id")),
            analysis_id=_optional_text(proposal_values.get("analysis_id")),
            action_type=action.value
            if action is not None
            else _optional_text(proposal_values.get("action_type")),
            connector_id=connector_id,
            reasons=reasons,
            evidence_references=proposal_evidence,
            attribution_references=proposal_attributions,
            validation_version=self.validation_version,
            authoritative_input_checksum=authoritative_checksum,
            proposal_checksum=proposal_checksum,
            validation_checksum=validation_checksum,
            replay_live_mode=_context_mode(context),
            provider=_context_provider(context),
            model=_context_model(context),
            policy_evaluation_ready=status is ProposalValidationStatus.VALID,
            audit_record={},
            canonical_action_identity=canonical_action_identity,
        )
        audit = {
            "outcome": status.value,
            "validation_version": self.validation_version,
            "tenant_id": result.tenant_id,
            "case_id": result.case_id,
            "analysis_id": result.analysis_id,
            "proposal_id": result.proposal_id,
            "action_type": result.action_type,
            "connector_id": result.connector_id,
            "reasons": list(result.reasons),
            "evidence_references": list(result.evidence_references),
            "attribution_references": list(result.attribution_references),
            "authoritative_input_checksum": result.authoritative_input_checksum,
            "proposal_checksum": result.proposal_checksum,
            "validation_checksum": result.validation_checksum,
            "replay_live_mode": result.replay_live_mode,
            "provider": result.provider,
            "model": result.model,
            "policy_evaluation_ready": result.policy_evaluation_ready,
            "canonical_action_identity": result.canonical_action_identity,
            "side_effects": False,
        }
        return replace(result, audit_record=audit)

    def _resolve_connector(
        self,
        action: ActionType,
        context: ProposalValidationContext,
        reasons: list[str],
    ) -> str | None:
        action_name = action.value
        connector_value: object | None = None
        declared_id = context.action_connector_ids.get(action_name)
        if declared_id is not None:
            connector_value = context.connectors.get(declared_id)
            if connector_value is None:
                connector_value = _registry_get(
                    context.connector_registry, context.tenant_id, declared_id
                )
            if connector_value is None:
                reasons.append("action connector is not declared for the tenant")
                return None
            connector_id = declared_id
        else:
            candidates: list[tuple[str, object]] = []
            for key, value in context.connectors.items():
                manifest = _manifest(value)
                if manifest is not None and action_name in _values(manifest, "operations"):
                    candidates.append((str(_value(manifest, "connector_id", key)), value))
            if len(candidates) != 1:
                reasons.append("action connector binding is missing or ambiguous")
                return None
            connector_id, connector_value = candidates[0]

        manifest = _manifest(connector_value)
        if manifest is None:
            reasons.append("action connector declaration is malformed")
            return None
        manifest_tenant = _value(manifest, "tenant_id")
        if manifest_tenant != context.tenant_id:
            reasons.append("action connector crosses the tenant boundary")
        manifest_id = _value(manifest, "connector_id")
        if manifest_id != connector_id:
            reasons.append("action connector identity does not match its declaration")
        if not _value(connector_value, "enabled", True):
            reasons.append("action connector is disabled")
        connector_type = _value(manifest, "connector_type")
        if _enum_value(connector_type) != ConnectorType.ACTION.value:
            reasons.append("connector is not an action connector")
        operations = set(_values(manifest, "operations"))
        resources = set(_values(manifest, "resources"))
        if action_name not in operations:
            reasons.append("action is not allowlisted by the connector")
        if action_name not in {item.value for item in ActionType}:
            reasons.append("action type is not approved")
        if any(
            not isinstance(value, str) or not value.strip() or _unsafe_identity(value)
            for value in (*operations, *resources)
        ):
            reasons.append("connector allowlist contains an unsafe declaration")
        if not operations.issubset(_ALLOWED_ACTION_OPERATIONS):
            reasons.append("connector allowlist contains an unsupported action operation")
        if not resources.issubset(_ALLOWED_CONNECTOR_RESOURCES):
            reasons.append("connector allowlist contains an unsupported resource")
        if _value(manifest, "schema_version") != CONTRACT_VERSION:
            reasons.append("action connector schema version is unsupported")
        if not _required_connector_resource(action).intersection(resources):
            reasons.append("action connector does not declare the required resource")
        return connector_id

    def _resolve_resource(
        self,
        target: object,
        action: ActionType,
        connector_id: str | None,
        context: ProposalValidationContext,
        reasons: list[str],
    ) -> object | None:
        if not isinstance(target, str) or not target.strip() or _unsafe_identity(target):
            reasons.append("target resource identity is malformed")
            return None
        resource = context.resources.get(target)
        if resource is None:
            reasons.append("target resource is not present in authoritative state")
            return None
        if target in context.ambiguous_resource_ids:
            reasons.append("target resource identity is ambiguous across authoritative connectors")
            return None
        resource_tenant = _value(resource, "tenant_id")
        resource_case = _value(resource, "case_id")
        if resource_tenant != context.tenant_id:
            reasons.append("target resource crosses the tenant boundary")
        if resource_case != context.case_id:
            reasons.append("target resource crosses the case boundary")
        resource_identity = _value(resource, "resource_id")
        if resource_identity != target:
            reasons.append("target resource identity does not match authoritative state")
        resource_type = _value(resource, "resource_type")
        if resource_type not in _required_connector_resource(action):
            reasons.append("target resource type is incompatible with the action")
        resource_connector = _value(resource, "connector_id")
        if not isinstance(resource_connector, str) or not resource_connector.strip():
            reasons.append("target resource has no authoritative connector binding")
        elif _unsafe_identity(resource_connector):
            reasons.append("target resource connector binding is malformed")
        elif connector_id is None or resource_connector != connector_id:
            reasons.append("target resource connector does not match resolved action connector")
        return resource

    def _check_references(
        self,
        evidence: tuple[str, ...],
        attributions: tuple[str, ...],
        resource: object | None,
        context: ProposalValidationContext,
        hard: list[str],
        escalation: list[str],
    ) -> None:
        if not evidence:
            hard.append("proposal requires evidence references")
        if not attributions:
            hard.append("proposal requires attribution references")
        known_evidence = set(context.evidence_references)
        for item in context.evidence_items:
            value = _value(item, "evidence_id")
            if isinstance(value, str) and value.strip():
                known_evidence.add(value)
        if not set(evidence).issubset(known_evidence):
            hard.append("proposal references unknown evidence")

        event_ids = set(context.timeline_events)
        if not set(attributions).issubset(event_ids):
            hard.append("proposal references unknown timeline events")
        target_timeline_ids = (
            set(_references(_value(resource, "timeline_event_ids", ()))) if resource else set()
        )
        resource_evidence = (
            set(_references(_value(resource, "evidence_references", ()))) if resource else set()
        )
        for event_id in attributions:
            event = context.timeline_events.get(event_id)
            if event is None:
                continue
            if _value(event, "tenant_id") not in (None, context.tenant_id):
                hard.append("timeline attribution crosses the tenant boundary")
            if _value(event, "case_id") not in (None, context.case_id):
                hard.append("timeline attribution crosses the case boundary")
            target_timeline_ids.update(_event_resource_timeline_ids(event, resource))
            event_evidence = set(_references(_value(event, "evidence_references", ())))
            resource_evidence.update(event_evidence)
            if event_evidence and not event_evidence.issubset(known_evidence):
                hard.append("authoritative timeline references unknown evidence")
            if _uncertain_event(event, context):
                escalation.append("proposal depends on uncertain timeline evidence")
        if resource is not None and not set(attributions).intersection(target_timeline_ids):
            hard.append("proposal attribution does not identify the target resource")
        if resource_evidence and not set(evidence).issubset(resource_evidence):
            hard.append("proposal evidence is not linked to the target resource")

        labels_by_event: dict[str, set[str]] = {}
        for event_id in attributions:
            values = context.attributions.get(event_id)
            if values is None:
                hard.append("proposal attribution is not present in authoritative analysis")
                continue
            candidates = (
                values
                if isinstance(values, Sequence) and not isinstance(values, str | bytes)
                else (values,)
            )
            for attribution in candidates:
                label = _enum_value(_value(attribution, "label"))
                labels_by_event.setdefault(event_id, set()).add(label)
                attribution_tenant = _value(attribution, "tenant_id")
                attribution_case = _value(attribution, "case_id")
                if attribution_tenant not in (None, context.tenant_id):
                    hard.append("attribution crosses the tenant boundary")
                if attribution_case not in (None, context.case_id):
                    hard.append("attribution crosses the case boundary")
                attr_evidence = set(_references(_value(attribution, "evidence_references", ())))
                if not attr_evidence.issubset(known_evidence):
                    hard.append("attribution references unknown evidence")
        if any(len(labels) > 1 for labels in labels_by_event.values()):
            escalation.append("conflicting attribution requires human review")
        target_labels = {
            label
            for event_id, labels in labels_by_event.items()
            if event_id in target_timeline_ids
            for label in labels
        }
        if AttributionLabel.LEGITIMATE.value in target_labels:
            hard.append("legitimate activity cannot be targeted")
        if not target_labels or target_labels <= {AttributionLabel.UNCERTAIN.value}:
            escalation.append("proposal is based only on uncertain attribution")
        elif AttributionLabel.UNCERTAIN.value in target_labels:
            escalation.append("uncertain attribution cannot authorize an action")

    def _check_action_preconditions(
        self,
        action: ActionType,
        proposal: Mapping[str, Any],
        resource: object | None,
        context: ProposalValidationContext,
        hard: list[str],
        escalation: list[str],
    ) -> None:
        if resource is None:
            return
        state = str(_value(resource, "state", "")).strip().lower()
        attributes = _resource_attributes(resource)
        if not isinstance(attributes, Mapping):
            hard.append("authoritative resource attributes are malformed")
            attributes = {}
        if action is ActionType.REVOKE_SUSPICIOUS_SESSION:
            if state in {"revoked", "closed", "expired", "deleted"}:
                hard.append("session is not in a revocable state")
            if attributes.get("implicated") is False:
                hard.append("session is not implicated by authoritative analysis")
        elif action is ActionType.HOLD_FULFILLMENT:
            if state in {
                "held",
                "cancelled",
                "canceled",
                "fulfilled",
                "shipped",
                "delivered",
                "completed",
            }:
                hard.append("fulfillment is not in a hold-compatible state")
        elif action is ActionType.CANCEL_ORDER:
            if state in {"cancelled", "canceled", "fulfilled", "shipped", "delivered", "completed"}:
                hard.append("order is not in a cancellable state")
        elif action is ActionType.REFUND_PAYMENT:
            self._check_refund(proposal, attributes, context, hard)
        elif action is ActionType.RESTORE_IDENTITY:
            if not any(
                attributes.get(name) is True
                for name in (
                    "previously_observed",
                    "approved_profile_change",
                    "approved_observed_change",
                )
            ):
                hard.append(
                    "identity restoration must reference an approved observed profile change"
                )
            if state in {"restored", "deleted"}:
                hard.append("profile change is not in a restorable state")
        if state in {"unknown", "stale", "unavailable"}:
            escalation.append("target resource state is stale or unresolved")

    def _check_refund(
        self,
        proposal: Mapping[str, Any],
        attributes: Mapping[str, Any],
        context: ProposalValidationContext,
        reasons: list[str],
    ) -> None:
        state = str(attributes.get("payment_state", attributes.get("state", ""))).strip().lower()
        if state != "captured":
            reasons.append("refund target is not an existing captured payment")
        source = attributes.get("payment_source", attributes.get("original_payment_source"))
        if (
            not isinstance(source, str)
            or not source.strip()
            or source.strip().lower()
            in {"unknown", "unknown_source", "unavailable", "not_provided"}
        ):
            reasons.append("refund target has no known original payment source")
        if (
            "original_payment_source" in attributes
            and attributes["original_payment_source"] != source
        ):
            reasons.append("refund target original payment source is inconsistent")
        amount = proposal.get("requested_amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            reasons.append("refund amount must be a positive integer minor-unit value")
        currency = proposal.get("currency")
        if (
            not isinstance(currency, str)
            or currency != currency.upper()
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
        ):
            reasons.append("refund currency must be an explicit uppercase ISO code")
        authoritative_currency = attributes.get("currency")
        exposure_currency = (
            _value(context.exposure, "currency") if context.exposure is not None else None
        )
        if not isinstance(authoritative_currency, str):
            authoritative_currency = exposure_currency
        if (
            not isinstance(authoritative_currency, str)
            or currency != authoritative_currency.upper()
        ):
            reasons.append("refund currency does not match authoritative currency")

        payment_amount = _minor_value(attributes.get("amount_minor"))
        reimbursed = _minor_value(attributes.get("reimbursed_minor", 0))
        if payment_amount is None or reimbursed is None or reimbursed > payment_amount:
            reasons.append("authoritative payment amount or reimbursement is malformed")
            return
        maximum = payment_amount - reimbursed
        exposure_remaining = _minor_value(_value(context.exposure, "remaining_exposure_minor"))
        if exposure_remaining is not None:
            maximum = min(maximum, exposure_remaining)
        if (
            amount is not None
            and isinstance(amount, int)
            and not isinstance(amount, bool)
            and amount > maximum
        ):
            reasons.append("refund amount exceeds authoritative recoverable exposure")
        if "destination" in attributes or "refund_destination" in attributes:
            reasons.append("refund destination must remain the original payment source")

    def _malformed_result(self, proposal: object, reason: str) -> ProposalValidationResult:
        proposal_values: dict[str, Any] = {}
        if isinstance(proposal, TypedActionProposal):
            proposal_values = _proposal_values(proposal, [])
        proposal_checksum = _checksum(proposal_values if proposal_values else repr(type(proposal)))
        input_checksum = _checksum({"context": "invalid"})
        validation_checksum = _checksum(
            {
                "validation_version": self.validation_version,
                "proposal_checksum": proposal_checksum,
                "authoritative_input_checksum": input_checksum,
                "status": ProposalValidationStatus.REJECTED.value,
                "reasons": (reason,),
            }
        )
        audit = {
            "outcome": ProposalValidationStatus.REJECTED.value,
            "validation_version": self.validation_version,
            "reasons": [reason],
            "proposal_checksum": proposal_checksum,
            "authoritative_input_checksum": input_checksum,
            "validation_checksum": validation_checksum,
            "policy_evaluation_ready": False,
            "provider": None,
            "model": None,
            "side_effects": False,
        }
        return ProposalValidationResult(
            status=ProposalValidationStatus.REJECTED,
            proposal_id=_optional_text(proposal_values.get("proposal_id")),
            tenant_id=_optional_text(proposal_values.get("tenant_id")),
            case_id=_optional_text(proposal_values.get("case_id")),
            analysis_id=_optional_text(proposal_values.get("analysis_id")),
            action_type=_optional_text(proposal_values.get("action_type")),
            connector_id=None,
            reasons=(reason,),
            evidence_references=(),
            attribution_references=(),
            validation_version=self.validation_version,
            authoritative_input_checksum=input_checksum,
            proposal_checksum=proposal_checksum,
            validation_checksum=validation_checksum,
            replay_live_mode=None,
            provider=None,
            model=None,
            policy_evaluation_ready=False,
            audit_record=audit,
            canonical_action_identity=None,
        )


DeterministicProposalValidator = ProposalValidator


def validate_proposal(
    proposal: object,
    context: ProposalValidationContext | Mapping[str, Any] | None = None,
    **context_values: Any,
) -> ProposalValidationResult:
    """Convenience function for the T075 deterministic validation boundary."""

    return ProposalValidator().validate(proposal, context, **context_values)


validate_typed_proposal = validate_proposal


_ACTION_RESOURCE_TYPES: dict[ActionType, frozenset[str]] = {
    ActionType.REVOKE_SUSPICIOUS_SESSION: frozenset({"sessions"}),
    ActionType.HOLD_FULFILLMENT: frozenset({"fulfillment"}),
    ActionType.CANCEL_ORDER: frozenset({"orders"}),
    ActionType.REFUND_PAYMENT: frozenset({"payments"}),
    ActionType.RESTORE_IDENTITY: frozenset({"profile_changes"}),
}
_ACTION_PARAMETER_KEYS: dict[ActionType, frozenset[str]] = {
    ActionType.REVOKE_SUSPICIOUS_SESSION: frozenset(
        {"reason", "revocation_reason", "review_reason"}
    ),
    ActionType.HOLD_FULFILLMENT: frozenset({"reason", "hold_reason", "review_reason"}),
    ActionType.CANCEL_ORDER: frozenset({"reason", "cancellation_reason"}),
    ActionType.REFUND_PAYMENT: frozenset({"reason", "refund_reason"}),
    ActionType.RESTORE_IDENTITY: frozenset({"reason", "restoration_reason"}),
}
_ALLOWED_ACTION_OPERATIONS = frozenset(action.value for action in ActionType)
_ALLOWED_CONNECTOR_RESOURCES = frozenset(
    resource for resources in _ACTION_RESOURCE_TYPES.values() for resource in resources
)
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "account",
        "api_key",
        "authorization",
        "bearer",
        "client_secret",
        "command",
        "connector",
        "cookie",
        "credential",
        "database",
        "destination",
        "device",
        "filesystem",
        "http",
        "network",
        "operation",
        "password",
        "private_key",
        "query",
        "raw_sql",
        "secret",
        "shell",
        "sql",
        "token",
        "tool",
        "transfer",
        "url",
    }
)
_FORBIDDEN_TEXT = (
    re.compile(r"\b(?:bash|cmd|powershell|pwsh|sh|curl|wget|invoke-webrequest)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:select|insert|update|delete|drop|alter)\b.{0,40}\b(?:from|into|table|where)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:https?|file)://", re.IGNORECASE),
)


def _proposal_values(proposal: object, reasons: list[str]) -> dict[str, Any]:
    if not isinstance(proposal, TypedActionProposal):
        return {}
    fields_set = set(TypedActionProposal.model_fields)
    raw_fields = set(getattr(proposal, "__dict__", {}))
    model_extra = getattr(proposal, "model_extra", None)
    if isinstance(model_extra, Mapping):
        raw_fields.update(model_extra)
    unknown = raw_fields - fields_set
    if unknown:
        reasons.append(f"proposal contains unsupported fields: {sorted(unknown)}")
    result: dict[str, Any] = {}
    for name in fields_set:
        try:
            result[name] = getattr(proposal, name)
        except AttributeError:
            reasons.append(f"proposal field {name} is missing")
    return result


def _check_direct_model_shape(proposal: TypedActionProposal, reasons: list[str]) -> None:
    if _value(proposal, "schema_version") != CONTRACT_VERSION:
        reasons.append("proposal schema version is unsupported")
    for name in (
        "proposal_id",
        "case_id",
        "tenant_id",
        "correlation_id",
        "analysis_id",
        "target_resource",
        "rationale",
        "idempotency_key",
    ):
        if not isinstance(_value(proposal, name), str) or not _value(proposal, name).strip():
            reasons.append(f"proposal {name} is required")


def _check_contract_identity(
    values: Mapping[str, Any], context: ProposalValidationContext, reasons: list[str]
) -> None:
    for name in ("tenant_id", "case_id", "correlation_id"):
        value = values.get(name)
        if not isinstance(value, str) or value != getattr(context, name):
            reasons.append(f"proposal {name} does not match authoritative scope")
        elif _unsafe_identity(value):
            reasons.append(f"proposal {name} identity is malformed")


def _check_analysis_binding(
    values: Mapping[str, Any], context: ProposalValidationContext, reasons: list[str]
) -> None:
    if values.get("analysis_id") != context.analysis_id:
        reasons.append("proposal analysis_id does not match the authoritative analysis")
    request = context.analysis_request
    if request is not None:
        if (
            not isinstance(request, ModelAnalysisRequest)
            or request.schema_version != CONTRACT_VERSION
        ):
            reasons.append("analysis request schema/version is unsupported")
        else:
            for name in ("tenant_id", "case_id", "correlation_id"):
                if getattr(request, name) != getattr(context, name):
                    reasons.append(f"analysis request {name} does not match authoritative scope")
    response = context.analysis_response
    if response is not None:
        if not isinstance(response, ModelAnalysisResponse):
            reasons.append("analysis response is not a typed response")
        else:
            if response.schema_version != CONTRACT_VERSION:
                reasons.append("analysis response schema/version is unsupported")
            for name in ("tenant_id", "correlation_id"):
                if getattr(response, name, None) != getattr(context, name):
                    reasons.append(f"analysis response {name} does not match authoritative scope")
            response_case = getattr(response, "case_id", None)
            if not isinstance(response_case, str) or response_case != context.case_id:
                reasons.append("analysis response is not bound to the authoritative case")
            response_analysis_id = getattr(response, "analysis_id", None)
            if response_analysis_id != context.analysis_id:
                reasons.append(
                    "analysis response identity does not match the authoritative analysis"
                )
            response_proposals = getattr(response, "proposals", ())
            if not any(
                _canonical(_proposal_values(item, [])) == _canonical(values)
                for item in response_proposals
            ):
                reasons.append("proposal is not the exact proposal returned by the analysis")
    provenance = context.analysis_provenance
    if provenance:
        for name, expected in (
            ("analysis_id", context.analysis_id),
            ("tenant_id", context.tenant_id),
            ("case_id", context.case_id),
            ("correlation_id", context.correlation_id),
        ):
            if provenance.get(name) != expected:
                reasons.append(f"analysis provenance {name} does not match authoritative scope")
        if context.provider is not None and provenance.get("provider") != context.provider:
            reasons.append("analysis provider provenance is inconsistent")
        if context.model is not None and provenance.get("model") != context.model:
            reasons.append("analysis model provenance is inconsistent")
    if context.response_checksum is not None and response is not None:
        if context.response_checksum != _checksum(response.model_dump(mode="json")):
            reasons.append("analysis response checksum is stale or inconsistent")


def _check_versions_and_mode(context: ProposalValidationContext, reasons: list[str]) -> None:
    if (
        context.analysis_input_version is not None
        and context.authoritative_analysis_input_version is not None
    ):
        if context.analysis_input_version != context.authoritative_analysis_input_version:
            reasons.append("analysis input version is stale")
    for key in sorted(set(context.input_versions) & set(context.authoritative_versions)):
        if context.input_versions[key] != context.authoritative_versions[key]:
            reasons.append(f"authoritative input version is stale: {key}")
    mode = _mode_value(context.provider_mode)
    replay_label = _mode_value(context.replay_label)
    if mode is not None and mode not in {item.value for item in ProviderMode}:
        reasons.append("provider mode is unsupported")
    if replay_label is not None and replay_label != mode:
        reasons.append("replay/live label does not match provider mode")
    if context.analysis_request is not None:
        request_mode = _mode_value(context.analysis_request.provider_mode)
        request_label = _mode_value(context.analysis_request.replay_label)
        if request_mode != request_label:
            reasons.append("analysis request replay/live label is inconsistent")
        if mode is not None and request_mode != mode:
            reasons.append("provider mode does not match the analysis request")
    for name, value in (("provider", context.provider), ("model", context.model)):
        if value is not None and (
            not isinstance(value, str) or not value.strip() or _unsafe_text(value)
        ):
            reasons.append(f"analysis {name} metadata is malformed")


def _check_parameters(value: object, action: ActionType | None, reasons: list[str]) -> None:
    if not isinstance(value, Mapping):
        reasons.append("proposal parameters must be an object")
        return
    if action is None:
        _scan_unsafe(value, reasons)
        return
    unknown = set(value) - set(_ACTION_PARAMETER_KEYS[action])
    if unknown:
        reasons.append("proposal parameters are not allowlisted: " f"{sorted(unknown, key=str)}")
    _scan_unsafe(value, reasons)
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            reasons.append("proposal parameter keys must be non-blank strings")
        if not _json_safe(item):
            reasons.append("proposal parameters must be JSON-compatible")


def _check_rationale(value: object, reasons: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        reasons.append("proposal rationale is required")
    elif _unsafe_text(value):
        reasons.append("proposal rationale contains a forbidden capability")


def _check_money(
    values: Mapping[str, Any],
    action: ActionType | None,
    context: ProposalValidationContext,
    reasons: list[str],
) -> None:
    amount = values.get("requested_amount_minor")
    currency = values.get("currency")
    if amount is not None and (
        isinstance(amount, bool) or not isinstance(amount, int) or amount < 0
    ):
        reasons.append("requested amount must be a non-negative integer minor-unit value")
    if currency is not None and (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        reasons.append("currency must be an explicit uppercase ISO code")
    if action is not ActionType.REFUND_PAYMENT and (amount is not None or currency is not None):
        reasons.append("money fields are only valid for refund proposals")
    if action is ActionType.REFUND_PAYMENT and (amount is None or currency is None):
        reasons.append("refund proposal requires amount and currency")
    if context.exposure is not None:
        exposure_currency = _value(context.exposure, "currency")
        if currency is not None and currency != exposure_currency:
            reasons.append("proposal currency does not match deterministic exposure currency")


def _check_idempotency(
    values: Mapping[str, Any],
    canonical_identity: str | None,
    context: ProposalValidationContext,
    reasons: list[str],
) -> None:
    supplied_key = values.get("idempotency_key")
    if (
        not isinstance(supplied_key, str)
        or not supplied_key.strip()
        or _unsafe_identity(supplied_key)
    ):
        reasons.append("idempotency identity is malformed")
        return
    if canonical_identity is None:
        reasons.append("canonical action identity cannot be derived from authoritative state")
        return

    # The supplied key remains T074 provenance only.  It never selects the
    # identity that downstream persistence and execution boundaries use.
    prior = context.existing_idempotency_keys.get(supplied_key)
    if prior is not None and prior != canonical_identity:
        reasons.append("idempotency key is already bound to a different action identity")
    canonical_prior = context.existing_idempotency_keys.get(canonical_identity)
    if canonical_prior is not None and canonical_prior != canonical_identity:
        reasons.append("canonical action identity is already bound to a different action")
    for existing_key, existing_identity in context.existing_idempotency_keys.items():
        if existing_key != canonical_identity and existing_identity == canonical_identity:
            reasons.append(
                "canonical action identity is already bound to a different idempotency key"
            )
            break


def _action_type(value: object, reasons: list[str]) -> ActionType | None:
    try:
        action = value if isinstance(value, ActionType) else ActionType(value)
    except (TypeError, ValueError):
        reasons.append("action type is unsupported")
        return None
    if action not in _ACTION_RESOURCE_TYPES:
        reasons.append("action type is not allowlisted")
        return None
    return action


def _required_connector_resource(action: ActionType) -> frozenset[str]:
    return _ACTION_RESOURCE_TYPES[action]


def _canonical_action_idempotency_key(
    values: Mapping[str, Any],
    *,
    action: ActionType,
    connector_id: str | None,
    resource: object | None,
    validation_version: str,
) -> str | None:
    """Derive a stable action key from trusted identity and semantic parameters."""

    resource_id = _value(resource, "resource_id") if resource is not None else None
    resource_type = _value(resource, "resource_type") if resource is not None else None
    resource_connector = _value(resource, "connector_id") if resource is not None else None
    if (
        not isinstance(connector_id, str)
        or _unsafe_identity(connector_id)
        or not isinstance(resource_id, str)
        or _unsafe_identity(resource_id)
        or not isinstance(resource_type, str)
        or _unsafe_identity(resource_type)
        or resource_connector != connector_id
    ):
        return None
    return _checksum(
        {
            "identity_version": ACTION_IDENTITY_VERSION,
            "schema_version": values.get("schema_version", CONTRACT_VERSION),
            "validation_version": validation_version,
            "tenant_id": values.get("tenant_id"),
            "case_id": values.get("case_id"),
            "analysis_id": values.get("analysis_id"),
            "action_type": action.value,
            "connector_id": connector_id,
            "target_resource": resource_id,
            "resource_type": resource_type,
            "parameters": values.get("parameters"),
            "requested_amount_minor": values.get("requested_amount_minor"),
            "currency": values.get("currency"),
        }
    )


def canonical_action_identity(
    proposal: TypedActionProposal,
    *,
    connector_id: str,
    resource: AuthoritativeResource,
    validation_version: str = PROPOSAL_VALIDATOR_VERSION,
) -> str:
    """Return the canonical key for an already-resolved authoritative action."""

    if not isinstance(proposal, TypedActionProposal):
        raise TypeError("proposal must be a TypedActionProposal")
    identity = _canonical_action_idempotency_key(
        proposal.model_dump(mode="json"),
        action=proposal.action_type,
        connector_id=connector_id,
        resource=resource,
        validation_version=validation_version,
    )
    if identity is None:
        raise ValueError("canonical action identity requires matching authoritative state")
    return identity


canonical_action_idempotency_key = canonical_action_identity


def _index_values(value: Mapping[str, object] | Sequence[object], name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str | bytes):
        raise ValueError(f"{name} values must be a mapping or sequence")
    result: dict[str, object] = {}
    for item in value:
        key = _value(item, name)
        if isinstance(key, str) and key.strip():
            result[key] = item
    return result


def _index_resources(
    value: Mapping[str, object] | Sequence[object],
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Index resource snapshots without silently collapsing duplicate identities."""

    if isinstance(value, Mapping):
        indexed = _index_values(value, "resource_id")
        identities: dict[str, int] = {}
        for item in value.values():
            resource_id = _value(item, "resource_id")
            if isinstance(resource_id, str) and resource_id.strip():
                identities[resource_id] = identities.get(resource_id, 0) + 1
        return indexed, tuple(
            sorted(identity for identity, count in identities.items() if count > 1)
        )
    if isinstance(value, str | bytes):
        raise ValueError("resource_id values must be a mapping or sequence")
    indexed: dict[str, object] = {}
    counts: dict[str, int] = {}
    for item in value:
        resource_id = _value(item, "resource_id")
        if isinstance(resource_id, str) and resource_id.strip():
            counts[resource_id] = counts.get(resource_id, 0) + 1
            indexed.setdefault(resource_id, item)
    return indexed, tuple(sorted(identity for identity, count in counts.items() if count > 1))


def _manifest(value: object) -> object | None:
    manifest = _value(value, "manifest")
    return manifest if manifest is not None else value


def _registry_get(registry: object | None, tenant_id: str, connector_id: str) -> object | None:
    if registry is None:
        return None
    getter = getattr(registry, "get", None)
    if getter is None or not callable(getter):
        return None
    try:
        return getter(tenant_id=tenant_id, connector_id=connector_id)
    except (KeyError, TypeError):
        try:
            return getter(tenant_id, connector_id)
        except (KeyError, TypeError):
            return None


def _event_resource_timeline_ids(event: object, resource: object | None) -> set[str]:
    result: set[str] = set()
    event_id = _value(event, "timeline_event_id")
    if isinstance(event_id, str):
        payload = _value(event, "event_payload", _value(event, "payload", {}))
        target = _value(resource, "resource_id") if resource else None
        if isinstance(payload, Mapping) and isinstance(target, str):
            action_resource_keys = (
                "session_id",
                "fulfillment_id",
                "order_id",
                "payment_id",
                "profile_change_id",
                "resource_id",
            )
            if any(payload.get(key) == target for key in action_resource_keys):
                result.add(event_id)
    return result


def _uncertain_event(event: object, context: ProposalValidationContext) -> bool:
    event_id = _value(event, "timeline_event_id")
    reasons = _references(_value(event, "uncertainty_reasons", ()))
    return bool(set(reasons) or event_id in context.uncertainty_references)


def _resource_attributes(resource: object) -> Mapping[str, Any]:
    value = _value(resource, "attributes", {})
    if not isinstance(value, Mapping):
        return value
    attributes = dict(value)
    if isinstance(resource, Mapping):
        for name in (
            "state",
            "payment_state",
            "amount_minor",
            "reimbursed_minor",
            "currency",
            "payment_source",
            "original_payment_source",
            "previously_observed",
            "approved_profile_change",
            "approved_observed_change",
            "implicated",
        ):
            if name in resource and name not in attributes:
                attributes[name] = resource[name]
    return attributes


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _values(value: object, name: str) -> tuple[object, ...]:
    raw = _value(value, name, ())
    if isinstance(raw, str | bytes) or raw is None:
        return ()
    try:
        return tuple(raw)  # type: ignore[arg-type]
    except TypeError:
        return ()


def _reference_values(value: object, name: str, reasons: list[str]) -> tuple[str, ...]:
    try:
        return _references(value)
    except ValueError as exc:
        reasons.append(str(exc) or f"{name} are malformed")
        return ()


def _references(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str | bytes):
        raise ValueError("references must be a sequence")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("references must be a sequence") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError("references contain an invalid identity")
    return tuple(sorted(set(item.strip() for item in values)))


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _mode_value(value: object) -> str | None:
    if value is None:
        return None
    return _enum_value(value)


def _enum_value(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _minor_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _unsafe_identity(value: object) -> bool:
    return not isinstance(value, str) or _unsafe_text(value) or not _IDENTITY_RE.fullmatch(value)


def _unsafe_text(value: object) -> bool:
    return not isinstance(value, str) or any(pattern.search(value) for pattern in _FORBIDDEN_TEXT)


def _unsafe_key(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _FORBIDDEN_KEY_PARTS or any(
        part in normalized for part in _FORBIDDEN_KEY_PARTS
    )


def _scan_unsafe(value: object, reasons: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _unsafe_key(key):
                reasons.append("proposal contains a forbidden capability or unbounded field")
            _scan_unsafe(item, reasons)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            _scan_unsafe(item, reasons)
    elif isinstance(value, str) and _unsafe_text(value):
        reasons.append("proposal contains a forbidden capability or untrusted endpoint")


def _json_safe(value: object) -> bool:
    if value is None or isinstance(value, str | int | bool):
        return True
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_safe(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return all(_json_safe(item) for item in value)
    return False


def _canonical(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_canonical(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonical(item) for item in value)
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(type(value))


def _checksum(value: object) -> str:
    encoded = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _authoritative_checksum(context: ProposalValidationContext) -> str:
    return _checksum(
        {
            "tenant_id": context.tenant_id,
            "case_id": context.case_id,
            "correlation_id": context.correlation_id,
            "analysis_id": context.analysis_id,
            "evidence_references": sorted(context.evidence_references),
            "evidence_items": context.evidence_items,
            "timeline_events": context.timeline_events,
            "attributions": context.attributions,
            "resources": context.resources,
            "connectors": context.connectors,
            "action_connector_ids": context.action_connector_ids,
            "exposure": context.exposure,
            "input_versions": context.input_versions,
            "authoritative_versions": context.authoritative_versions,
            "analysis_input_version": context.analysis_input_version,
            "authoritative_analysis_input_version": context.authoritative_analysis_input_version,
            "response_checksum": context.response_checksum,
            "analysis_request": context.analysis_request,
            "analysis_response": context.analysis_response,
            "analysis_provenance": context.analysis_provenance,
            "uncertainty_references": sorted(context.uncertainty_references),
            "provider": context.provider,
            "model": context.model,
            "provider_mode": context.provider_mode,
            "replay_label": context.replay_label,
        }
    )


def _context_mode(context: ProposalValidationContext) -> str | None:
    return _mode_value(
        context.provider_mode
        if context.provider_mode is not None
        else _value(context.analysis_request, "provider_mode")
    )


def _context_provider(context: ProposalValidationContext) -> str | None:
    return context.provider or _optional_text(_value(context.analysis_response, "provider"))


def _context_model(context: ProposalValidationContext) -> str | None:
    return context.model or _optional_text(_value(context.analysis_response, "model"))


def _stable_reasons(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if isinstance(value, str) and value.strip()}))


__all__ = [
    "AttributionState",
    "AuthoritativeAttribution",
    "AuthoritativeProposalState",
    "AuthoritativeResource",
    "ACTION_IDENTITY_VERSION",
    "canonical_action_identity",
    "canonical_action_idempotency_key",
    "DeterministicProposalValidator",
    "ProposalValidationContext",
    "ProposalValidationResult",
    "ProposalValidationStatus",
    "ProposalValidator",
    "PROPOSAL_VALIDATOR_VERSION",
    "ResourceState",
    "ValidationStatus",
    "validate_proposal",
    "validate_typed_proposal",
]
