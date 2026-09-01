"""Authoritative, redacted persistence values for bounded model analysis.

The model boundary is advisory.  This module turns an already parsed response and
already validated proposal results into an immutable persistence value.  It does
not call a provider, evaluate policy, or execute a proposal.  The PostgreSQL
repository is the only component that persists the value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from finance.exposure import FinancialExposure
from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelAnalysisResponse,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.common import CONTRACT_VERSION

MODEL_ANALYSIS_AUDIT_VERSION = "model-analysis-audit-v1.0.0"
MODEL_RUN_SCHEMA_VERSION = "model-run-v1.0.0"


class ModelAnalysisPersistenceError(ValueError):
    """The model result cannot cross the authoritative persistence boundary."""


@dataclass(frozen=True, slots=True)
class PersistedProposal:
    """A typed proposal and its deterministic T075 validation outcome.

    ``execution_state`` and ``approval_state`` are deliberately fixed advisory
    values.  Policy and approval are later US3 responsibilities.
    """

    proposal: TypedActionProposal
    validation_status: str
    validation_version: str
    validation_checksum: str
    authoritative_input_checksum: str
    proposal_checksum: str
    validation_reasons: tuple[str, ...] = ()
    policy_evaluation_ready: bool = False
    execution_state: str = "not_executable"
    approval_state: str = "not_approved"
    canonical_action_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, TypedActionProposal):
            raise ModelAnalysisPersistenceError("persisted proposal must be typed")
        _required_text(self.validation_status, "proposal validation status")
        if self.validation_status not in {"valid", "rejected", "escalation_only"}:
            raise ModelAnalysisPersistenceError("proposal validation status is unsupported")
        _required_text(self.validation_version, "proposal validation version")
        for name in (
            "validation_checksum",
            "authoritative_input_checksum",
            "proposal_checksum",
        ):
            _checksum_text(getattr(self, name), name)
        if any(
            not isinstance(reason, str) or not reason.strip() for reason in self.validation_reasons
        ):
            raise ModelAnalysisPersistenceError("proposal validation reasons must be non-blank")
        expected_ready = self.validation_status == "valid"
        if self.policy_evaluation_ready is not expected_ready:
            raise ModelAnalysisPersistenceError(
                "proposal policy readiness does not match validation status"
            )
        if self.execution_state != "not_executable":
            raise ModelAnalysisPersistenceError(
                "model proposals are never executable at persistence"
            )
        if self.approval_state != "not_approved":
            raise ModelAnalysisPersistenceError("model proposals are never approved at persistence")
        if self.validation_status == "valid" and self.canonical_action_identity is None:
            raise ModelAnalysisPersistenceError(
                "valid proposal persistence requires a canonical action identity"
            )
        if self.canonical_action_identity is not None:
            _checksum_text(self.canonical_action_identity, "canonical_action_identity")
            if self.proposal.idempotency_key != self.canonical_action_identity:
                raise ModelAnalysisPersistenceError(
                    "persisted proposal idempotency key is not canonical"
                )

    @classmethod
    def from_validation(
        cls, proposal: TypedActionProposal, validation: object
    ) -> PersistedProposal:
        """Build a persistence record from the deterministic T075 result only."""

        from analysis.proposal_validator import ProposalValidationResult

        if not isinstance(proposal, TypedActionProposal):
            raise ModelAnalysisPersistenceError("proposal must be a TypedActionProposal")
        if not isinstance(validation, ProposalValidationResult):
            raise ModelAnalysisPersistenceError(
                "proposal persistence requires a deterministic validation result"
            )
        proposal_id = getattr(validation, "proposal_id", None)
        if proposal_id != proposal.proposal_id:
            raise ModelAnalysisPersistenceError(
                "proposal validation identity does not match proposal"
            )
        for name, expected in (
            ("tenant_id", proposal.tenant_id),
            ("case_id", proposal.case_id),
            ("analysis_id", proposal.analysis_id),
        ):
            actual = getattr(validation, name, None)
            if actual != expected:
                raise ModelAnalysisPersistenceError(
                    f"proposal validation {name} does not match proposal"
                )
        status = _enum_value(validation.status)
        canonical_identity = getattr(validation, "canonical_action_identity", None)
        if canonical_identity is not None:
            try:
                proposal = proposal.model_copy(update={"idempotency_key": canonical_identity})
            except (TypeError, ValueError) as exc:
                raise ModelAnalysisPersistenceError(
                    "canonical action identity cannot be applied to proposal"
                ) from exc
        return cls(
            proposal=proposal,
            validation_status=status,
            validation_version=_required_text(validation.validation_version, "validation_version"),
            validation_checksum=_checksum_text(
                validation.validation_checksum, "validation_checksum"
            ),
            authoritative_input_checksum=_checksum_text(
                validation.authoritative_input_checksum, "authoritative_input_checksum"
            ),
            proposal_checksum=_checksum_text(validation.proposal_checksum, "proposal_checksum"),
            validation_reasons=tuple(validation.reasons),
            policy_evaluation_ready=bool(validation.policy_evaluation_ready),
            canonical_action_identity=canonical_identity,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal": _jsonable(self.proposal),
            "validation_status": self.validation_status,
            "validation_version": self.validation_version,
            "validation_checksum": self.validation_checksum,
            "authoritative_input_checksum": self.authoritative_input_checksum,
            "proposal_checksum": self.proposal_checksum,
            "validation_reasons": list(self.validation_reasons),
            "policy_evaluation_ready": self.policy_evaluation_ready,
            "execution_state": self.execution_state,
            "approval_state": self.approval_state,
            "canonical_action_identity": self.canonical_action_identity,
        }


@dataclass(frozen=True, slots=True)
class ModelAnalysisAudit:
    """Validated model-run persistence value with complete tenant/case binding."""

    tenant_id: str
    case_id: str
    correlation_id: str
    deterministic_seed: str
    analysis_id: str
    mode: str
    replay_label: str
    provider: str
    model: str
    adapter_version: str
    request_schema_version: str
    response_schema_version: str
    parser_version: str
    request_checksum: str
    response_checksum: str
    deterministic_analysis_checksum: str
    deterministic_exposure_checksum: str
    input_references: tuple[str, ...]
    output_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    timeline_references: tuple[str, ...]
    attribution_versions: tuple[str, ...]
    feature_schema_version: str | None
    exposure_version: str
    exposure_currency: str
    gross_exposure_minor: int
    recoverable_value_minor: int
    contained_value_minor: int
    legitimate_value_disrupted_minor: int
    irreversible_loss_minor: int
    remaining_exposure_minor: int
    uncertainty: tuple[str, ...]
    refusal_records: tuple[str, ...]
    forbidden_attempts: tuple[str, ...]
    proposals: tuple[PersistedProposal, ...]
    provenance: Mapping[str, Any]
    created_at: datetime
    validated: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "case_id",
            "correlation_id",
            "deterministic_seed",
            "analysis_id",
            "mode",
            "replay_label",
            "provider",
            "model",
            "adapter_version",
            "request_schema_version",
            "response_schema_version",
            "parser_version",
            "exposure_version",
            "exposure_currency",
        ):
            _required_text(getattr(self, name), name)
        if self.mode not in {ProviderMode.LIVE.value, ProviderMode.REPLAY.value}:
            raise ModelAnalysisPersistenceError("model analysis mode is unsupported")
        if self.replay_label != self.mode:
            raise ModelAnalysisPersistenceError("model analysis mode and replay label differ")
        for name in (
            "request_checksum",
            "response_checksum",
            "deterministic_analysis_checksum",
            "deterministic_exposure_checksum",
        ):
            _checksum_text(getattr(self, name), name)
        if (
            len(self.exposure_currency) != 3
            or not self.exposure_currency.isascii()
            or not self.exposure_currency.isalpha()
            or self.exposure_currency != self.exposure_currency.upper()
        ):
            raise ModelAnalysisPersistenceError("exposure currency is not an uppercase ISO code")
        for name in (
            "gross_exposure_minor",
            "recoverable_value_minor",
            "contained_value_minor",
            "legitimate_value_disrupted_minor",
            "irreversible_loss_minor",
            "remaining_exposure_minor",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ModelAnalysisPersistenceError(f"{name} must be a non-negative integer")
        if (
            self.recoverable_value_minor > self.gross_exposure_minor
            or self.contained_value_minor > self.recoverable_value_minor
            or self.irreversible_loss_minor
            != self.gross_exposure_minor - self.recoverable_value_minor
            or self.remaining_exposure_minor
            != self.recoverable_value_minor - self.contained_value_minor
        ):
            raise ModelAnalysisPersistenceError(
                "model analysis exposure arithmetic is inconsistent"
            )
        if not isinstance(self.created_at, datetime):
            raise ModelAnalysisPersistenceError("created_at must be a datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ModelAnalysisPersistenceError("created_at requires an explicit timezone")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        for name in (
            "input_references",
            "output_references",
            "evidence_references",
            "timeline_references",
            "attribution_versions",
            "uncertainty",
            "refusal_records",
            "forbidden_attempts",
        ):
            object.__setattr__(self, name, _references(getattr(self, name), name))
        proposals = tuple(self.proposals)
        if any(not isinstance(item, PersistedProposal) for item in proposals):
            raise ModelAnalysisPersistenceError("model analysis proposals must be persisted values")
        proposal_ids = tuple(item.proposal.proposal_id for item in proposals)
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ModelAnalysisPersistenceError("model analysis proposal identities must be unique")
        if not isinstance(self.validated, bool):
            raise ModelAnalysisPersistenceError("model analysis validation state is invalid")
        object.__setattr__(self, "proposals", proposals)
        if not isinstance(self.provenance, Mapping):
            raise ModelAnalysisPersistenceError("model analysis provenance must be an object")
        object.__setattr__(self, "provenance", _jsonable(dict(self.provenance)))

    @classmethod
    def from_result(
        cls,
        result: object,
        *,
        proposal_validations: Mapping[str, object] | Sequence[object] = (),
        authoritative_exposure: object | None = None,
        created_at: datetime | None = None,
    ) -> ModelAnalysisAudit:
        """Create a persistable value from deterministic output and T074/T075 values.

        The function intentionally requires the typed response and validation
        results.  A caller cannot use the PostgreSQL repository as a shortcut
        around response parsing or proposal validation.
        """

        request = getattr(result, "analysis_request", None)
        response = getattr(result, "analysis_response", None)
        if not isinstance(request, ModelAnalysisRequest):
            raise ModelAnalysisPersistenceError("model analysis request is required")
        if not isinstance(response, ModelAnalysisResponse):
            raise ModelAnalysisPersistenceError("typed model analysis response is required")
        if request.schema_version != CONTRACT_VERSION:
            raise ModelAnalysisPersistenceError("analysis request schema version is unsupported")
        if response.schema_version != CONTRACT_VERSION:
            raise ModelAnalysisPersistenceError("analysis response schema version is unsupported")
        if request.provider_mode.value != request.replay_label.value:
            raise ModelAnalysisPersistenceError("analysis mode and replay label do not match")
        _require_scope(result, request, response)
        response_case_id = getattr(response, "case_id", None)
        if response_case_id != request.case_id:
            raise ModelAnalysisPersistenceError("typed response must carry the authoritative case")

        exposure = getattr(result, "exposure", None)
        if not isinstance(exposure, FinancialExposure):
            raise ModelAnalysisPersistenceError("typed deterministic exposure is required")
        if authoritative_exposure is not None and authoritative_exposure != exposure:
            raise ModelAnalysisPersistenceError(
                "deterministic exposure does not match analysis result"
            )
        _validate_exposure_scope(exposure, request)

        proposals = _proposal_validations(response, proposal_validations)
        request_dump = request.model_dump(mode="json")
        response_dump = response.model_dump(mode="json")
        deterministic_checksum = _checksum(
            {
                "tenant_id": request.tenant_id,
                "case_id": request.case_id,
                "correlation_id": request.correlation_id,
                "deterministic_seed": str(getattr(result, "deterministic_seed", "")),
                "attributions": _jsonable(getattr(result, "attributions", ())),
                "exposure": _jsonable(exposure),
                "uncertainty": tuple(getattr(result, "uncertainty", ())),
            }
        )
        exposure_checksum = _checksum(_exposure_dump(exposure))
        metadata = getattr(result, "metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        computed_response_checksum = _checksum(response_dump)
        supplied_response_checksum = metadata.get("analysis_response_checksum")
        response_checksum = computed_response_checksum
        if supplied_response_checksum is not None:
            response_checksum = _checksum_text(supplied_response_checksum, "response_checksum")
            if response_checksum != computed_response_checksum:
                raise ModelAnalysisPersistenceError(
                    "analysis response checksum does not match typed response"
                )
        parser_version = str(
            metadata.get("analysis_parser_version") or "analysis-output-parser-unknown"
        )
        adapter_version = str(
            metadata.get("analysis_adapter_version") or "provider-adapter-unknown"
        )
        input_references = _references(
            tuple(getattr(request, "evidence_references", ()))
            + tuple(_timeline_ids(request))
            + tuple(getattr(result, "outcome_record", {}).get("input_references", ())),
            "input_references",
        )
        timeline_references = _timeline_ids(request)
        evidence_references = _references(
            tuple(getattr(request, "evidence_references", ()))
            + tuple(
                reference
                for item in request.redacted_case_representation.get("timeline", ())
                if isinstance(item, Mapping)
                for reference in item.get("evidence_references", ())
            ),
            "evidence_references",
        )
        output_references = _references(
            tuple(metadata.get("analysis_output_references", ()))
            + (f"analysis:{response.analysis_id}",)
            + tuple(f"proposal:{item.proposal.proposal_id}" for item in proposals),
            "output_references",
        )
        refusals = _references(response.refusal_records, "refusal_records")
        forbidden = _references(
            tuple(getattr(result, "forbidden_attempts", ())) + refusals,
            "forbidden_attempts",
        )
        attributions = tuple(getattr(result, "attributions", ()))
        attribution_versions = _references(
            tuple(
                str(value.model_or_rules_version)
                for value in attributions
                if getattr(value, "model_or_rules_version", None)
            ),
            "attribution_versions",
        )
        return cls(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            correlation_id=request.correlation_id,
            deterministic_seed=_required_text(
                getattr(result, "deterministic_seed", None), "deterministic_seed"
            ),
            analysis_id=response.analysis_id,
            mode=request.provider_mode.value,
            replay_label=request.replay_label.value,
            provider=_required_text(response.provider, "provider"),
            model=_required_text(response.model, "model"),
            adapter_version=adapter_version,
            request_schema_version=request.schema_version,
            response_schema_version=response.schema_version,
            parser_version=parser_version,
            request_checksum=_checksum(request_dump),
            response_checksum=_checksum_text(response_checksum, "response_checksum"),
            deterministic_analysis_checksum=deterministic_checksum,
            deterministic_exposure_checksum=exposure_checksum,
            input_references=input_references,
            output_references=output_references,
            evidence_references=evidence_references,
            timeline_references=timeline_references,
            attribution_versions=attribution_versions,
            feature_schema_version=getattr(result, "feature_schema_version", None),
            exposure_version=_required_text(exposure.calculation_version, "exposure_version"),
            exposure_currency=_required_text(exposure.currency, "exposure_currency"),
            gross_exposure_minor=exposure.gross_exposure_minor,
            recoverable_value_minor=exposure.recoverable_value_minor,
            contained_value_minor=exposure.contained_value_minor,
            legitimate_value_disrupted_minor=exposure.legitimate_value_disrupted_minor,
            irreversible_loss_minor=exposure.irreversible_loss_minor,
            remaining_exposure_minor=exposure.remaining_exposure_minor,
            uncertainty=_references(getattr(result, "uncertainty", ()), "uncertainty"),
            refusal_records=refusals,
            forbidden_attempts=forbidden,
            proposals=proposals,
            provenance={
                "audit_version": MODEL_ANALYSIS_AUDIT_VERSION,
                "model_run_schema_version": MODEL_RUN_SCHEMA_VERSION,
                "deterministic_seed": _required_text(
                    getattr(result, "deterministic_seed", None), "deterministic_seed"
                ),
                "request_schema_version": request.schema_version,
                "response_schema_version": response.schema_version,
                "parser_version": parser_version,
                "provider": response.provider,
                "model": response.model,
                "mode": request.provider_mode.value,
                "replay_label": request.replay_label.value,
                "policy_version_id": request.policy_version_id,
                "deterministic_analysis_version": getattr(result, "outcome_record", {}).get(
                    "analysis_version"
                ),
                "exposure_version": exposure.calculation_version,
                "request_checksum": _checksum(request_dump),
                "response_checksum": _checksum_text(response_checksum, "response_checksum"),
                "deterministic_analysis_checksum": deterministic_checksum,
                "deterministic_exposure_checksum": exposure_checksum,
                "authoritative_store": "postgresql",
                "side_effects": False,
            },
            created_at=created_at or datetime.now(UTC),
            validated=True,
        )

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        return tuple(item.proposal.proposal_id for item in self.proposals)

    def as_dict(self) -> dict[str, Any]:
        """Return the redacted, JSON-compatible persistence/audit payload."""

        return {
            "tenant_id": self.tenant_id,
            "case_id": self.case_id,
            "correlation_id": self.correlation_id,
            "deterministic_seed": self.deterministic_seed,
            "analysis_id": self.analysis_id,
            "mode": self.mode,
            "replay_label": self.replay_label,
            "provider": self.provider,
            "model": self.model,
            "adapter_version": self.adapter_version,
            "request_schema_version": self.request_schema_version,
            "response_schema_version": self.response_schema_version,
            "parser_version": self.parser_version,
            "request_checksum": self.request_checksum,
            "response_checksum": self.response_checksum,
            "deterministic_analysis_checksum": self.deterministic_analysis_checksum,
            "deterministic_exposure_checksum": self.deterministic_exposure_checksum,
            "input_references": list(self.input_references),
            "output_references": list(self.output_references),
            "evidence_references": list(self.evidence_references),
            "timeline_references": list(self.timeline_references),
            "attribution_versions": list(self.attribution_versions),
            "feature_schema_version": self.feature_schema_version,
            "exposure_version": self.exposure_version,
            "exposure_currency": self.exposure_currency,
            "gross_exposure_minor": self.gross_exposure_minor,
            "recoverable_value_minor": self.recoverable_value_minor,
            "contained_value_minor": self.contained_value_minor,
            "legitimate_value_disrupted_minor": self.legitimate_value_disrupted_minor,
            "irreversible_loss_minor": self.irreversible_loss_minor,
            "remaining_exposure_minor": self.remaining_exposure_minor,
            "uncertainty": list(self.uncertainty),
            "refusal_records": list(self.refusal_records),
            "forbidden_attempts": list(self.forbidden_attempts),
            "proposal_ids": list(self.proposal_ids),
            "provenance": _jsonable(self.provenance),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def audit_action(self) -> str:
        return "model.analysis.persisted"

    @property
    def audit_outcome(self) -> str:
        return self.mode

    def build_audit_record(
        self,
        audit_chain: object,
        *,
        audit_id: str,
        actor: str = "model-gateway",
        recorded_at: datetime | None = None,
    ) -> object:
        """Build an append-only record through the existing serialized audit chain."""

        if not self.validated:
            raise ModelAnalysisPersistenceError("unvalidated model analysis cannot be audited")
        builder = getattr(audit_chain, "build_record", None)
        if builder is None:
            raise TypeError("audit_chain must provide build_record")
        output_references = (*self.output_references, *self._attempt_references())
        return builder(
            tenant_id=self.tenant_id,
            audit_id=_required_text(audit_id, "audit_id"),
            case_id=self.case_id,
            actor=_required_text(actor, "actor"),
            action=self.audit_action,
            input_references=self.input_references,
            output_references=output_references,
            evidence_references=self.evidence_references,
            policy_version_id=str(self.provenance.get("policy_version_id"))
            if self.provenance.get("policy_version_id")
            else None,
            model_version=self.model,
            provider_version=self.adapter_version,
            correlation_ids=(self.correlation_id,),
            outcome=self.audit_outcome,
            recorded_at=recorded_at or self.created_at,
        )

    def append_audit_record(
        self,
        audit_chain: object,
        *,
        audit_id: str,
        actor: str = "model-gateway",
        recorded_at: datetime | None = None,
    ) -> object:
        """Build and append through the existing checksum-linked audit chain."""

        record = self.build_audit_record(
            audit_chain,
            audit_id=audit_id,
            actor=actor,
            recorded_at=recorded_at,
        )
        append = getattr(audit_chain, "append", None)
        if append is None:
            raise TypeError("audit_chain must provide append")
        return append(record)

    def _attempt_references(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *(f"refusal:{value}" for value in self.refusal_records),
                    *(f"forbidden_attempt:{value}" for value in self.forbidden_attempts),
                }
            )
        )


def build_model_analysis_audit(
    result: object,
    *,
    proposal_validations: Mapping[str, object] | Sequence[object] = (),
    authoritative_exposure: object | None = None,
    created_at: datetime | None = None,
) -> ModelAnalysisAudit:
    """Stable functional entry point for T076 callers."""

    return ModelAnalysisAudit.from_result(
        result,
        proposal_validations=proposal_validations,
        authoritative_exposure=authoritative_exposure,
        created_at=created_at,
    )


def _proposal_validations(
    response: ModelAnalysisResponse,
    values: Mapping[str, object] | Sequence[object],
) -> tuple[PersistedProposal, ...]:
    if isinstance(values, Mapping):
        indexed = dict(values)
        expected_ids = {proposal.proposal_id for proposal in response.proposals}
        if set(indexed) != expected_ids:
            raise ModelAnalysisPersistenceError(
                "proposal validation identities do not match typed proposals"
            )
        ordered = [indexed.get(proposal.proposal_id) for proposal in response.proposals]
    else:
        ordered_values = tuple(values)
        ordered = list(ordered_values)
        if len(ordered) != len(response.proposals):
            raise ModelAnalysisPersistenceError(
                "every typed proposal requires exactly one deterministic validation result"
            )
    if len(ordered) != len(response.proposals):
        raise ModelAnalysisPersistenceError(
            "every typed proposal requires exactly one deterministic validation result"
        )
    result: list[PersistedProposal] = []
    canonical_identities: set[str] = set()
    for proposal, validation in zip(response.proposals, ordered, strict=True):
        if validation is None:
            raise ModelAnalysisPersistenceError(
                f"proposal {proposal.proposal_id} has no deterministic validation result"
            )
        persisted = PersistedProposal.from_validation(proposal, validation)
        if persisted.validation_status == "valid" and persisted.canonical_action_identity:
            if persisted.canonical_action_identity in canonical_identities:
                raise ModelAnalysisPersistenceError(
                    "semantically duplicate valid action identities are not persistable"
                )
            canonical_identities.add(persisted.canonical_action_identity)
        result.append(persisted)
    return tuple(result)


def _require_scope(
    result: object, request: ModelAnalysisRequest, response: ModelAnalysisResponse
) -> None:
    for name in ("tenant_id", "case_id", "correlation_id"):
        expected = getattr(request, name)
        if getattr(result, name, None) != expected:
            raise ModelAnalysisPersistenceError(f"analysis result {name} does not match request")
        if getattr(response, name, None) != expected:
            raise ModelAnalysisPersistenceError(f"analysis response {name} does not match request")


def _validate_exposure_scope(exposure: object, request: ModelAnalysisRequest) -> None:
    if getattr(exposure, "tenant_id", None) != request.tenant_id:
        raise ModelAnalysisPersistenceError("deterministic exposure crosses the tenant boundary")
    if getattr(exposure, "case_id", None) != request.case_id:
        raise ModelAnalysisPersistenceError("deterministic exposure crosses the case boundary")


def _timeline_ids(request: ModelAnalysisRequest) -> tuple[str, ...]:
    values = request.redacted_case_representation.get("timeline", ())
    return _references(
        tuple(
            item["timeline_event_id"]
            for item in values
            if isinstance(item, Mapping) and isinstance(item.get("timeline_event_id"), str)
        ),
        "timeline_references",
    )


def _exposure_dump(value: object) -> dict[str, Any]:
    return {
        name: _jsonable(getattr(value, name))
        for name in (
            "tenant_id",
            "case_id",
            "currency",
            "gross_exposure_minor",
            "recoverable_value_minor",
            "contained_value_minor",
            "legitimate_value_disrupted_minor",
            "irreversible_loss_minor",
            "remaining_exposure_minor",
            "calculation_version",
            "source_references",
            "uncertain_source_references",
            "payment_references",
        )
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in dataclass_fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, str | bytes | int | float | bool):
        return _jsonable(value.value)
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {
            key: _jsonable(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    return value


def _checksum(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _checksum_text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value.lower())
    ):
        raise ModelAnalysisPersistenceError(f"{name} must be a SHA-256 checksum")
    return value.lower()


def _references(value: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ModelAnalysisPersistenceError(f"{name} must be a sequence")
    values = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ModelAnalysisPersistenceError(f"{name} contains an invalid reference")
    return tuple(sorted(set(item.strip() for item in values)))


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelAnalysisPersistenceError(f"{name} is required")
    return value.strip()


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    return _required_text(candidate, "enum value")


__all__ = [
    "MODEL_ANALYSIS_AUDIT_VERSION",
    "MODEL_RUN_SCHEMA_VERSION",
    "ModelAnalysisAudit",
    "ModelAnalysisPersistenceError",
    "PersistedProposal",
    "build_model_analysis_audit",
]
