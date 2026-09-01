"""Deterministic financial exposure accounting in integer minor units."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from packages.contracts.analysis_policy import AttributionLabel


class ExposureValidationError(ValueError):
    """Raised when an exposure input cannot be trusted or bounded."""


@dataclass(frozen=True, slots=True)
class FinancialExposure:
    """A reproducible case-level exposure result.

    ``gross_exposure_minor`` includes only confirmed malicious captured payments.
    Reimbursement is the irreversible component, while containment reduces the
    remaining recoverable exposure.  Legitimate disruption is tracked separately.
    """

    tenant_id: str
    case_id: str
    currency: str
    gross_exposure_minor: int
    recoverable_value_minor: int
    contained_value_minor: int
    legitimate_value_disrupted_minor: int
    irreversible_loss_minor: int
    remaining_exposure_minor: int
    calculation_version: str
    source_references: tuple[str, ...] = field(default_factory=tuple)
    uncertain_source_references: tuple[str, ...] = field(default_factory=tuple)
    payment_references: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "case_id", "currency", "calculation_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ExposureValidationError(f"exposure {name} is required")
        if (
            len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise ExposureValidationError("exposure currency must be an uppercase ISO code")
        integer_fields = (
            "gross_exposure_minor",
            "recoverable_value_minor",
            "contained_value_minor",
            "legitimate_value_disrupted_minor",
            "irreversible_loss_minor",
            "remaining_exposure_minor",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ExposureValidationError(f"exposure {name} must be a non-negative integer")
        if self.recoverable_value_minor > self.gross_exposure_minor:
            raise ExposureValidationError("recoverable exposure exceeds gross exposure")
        if self.contained_value_minor > self.recoverable_value_minor:
            raise ExposureValidationError("contained value exceeds recoverable exposure")
        if self.irreversible_loss_minor != (
            self.gross_exposure_minor - self.recoverable_value_minor
        ):
            raise ExposureValidationError("irreversible loss does not match reimbursement")
        if self.remaining_exposure_minor != (
            self.recoverable_value_minor - self.contained_value_minor
        ):
            raise ExposureValidationError("remaining exposure does not match containment")
        object.__setattr__(self, "source_references", _references(self.source_references))
        object.__setattr__(
            self,
            "uncertain_source_references",
            _references(self.uncertain_source_references),
        )
        object.__setattr__(self, "payment_references", _references(self.payment_references))


def calculate_exposure(
    *,
    tenant_id: str,
    case_id: str,
    payments: Sequence[object],
    calculation_version: str,
    currency: str | None = None,
) -> FinancialExposure:
    """Calculate exposure from trusted, case-linked captured payment facts.

    Inputs with a non-captured state, missing case/source/currency, conflicting
    currencies or duplicate identities with different values fail closed.  Legitimate
    and uncertain payments are validated for provenance but never added to fraud loss.
    """

    _required_text(tenant_id, "tenant_id")
    _required_text(case_id, "case_id")
    _required_text(calculation_version, "calculation_version")
    requested_currency = _currency(currency, allow_none=True)

    normalized: dict[str, dict[str, Any]] = {}
    timeline_to_payment: dict[str, str] = {}
    for index, value in enumerate(payments):
        item = _normalize_payment(value, index=index, tenant_id=tenant_id, case_id=case_id)
        item_currency = item["currency"]
        if requested_currency is None:
            requested_currency = item_currency
        elif item_currency != requested_currency:
            raise ExposureValidationError("exposure inputs contain multiple currencies")

        payment_id = item["payment_id"]
        timeline_event_id = item["timeline_event_id"]
        previous_timeline_payment = timeline_to_payment.get(timeline_event_id)
        if previous_timeline_payment is not None and previous_timeline_payment != payment_id:
            raise ExposureValidationError("timeline event maps to multiple payment identities")
        timeline_to_payment[timeline_event_id] = payment_id

        previous = normalized.get(payment_id)
        if previous is None:
            normalized[payment_id] = item
        elif not _same_payment_facts(previous, item):
            raise ExposureValidationError("duplicate payment identity has conflicting facts")
        else:
            previous["timeline_references"].update(item["timeline_references"])
            previous["evidence_references"].update(item["evidence_references"])

    if requested_currency is None:
        raise ExposureValidationError("currency is required when there are no payment inputs")

    gross = 0
    recoverable = 0
    contained = 0
    legitimate_disrupted = 0
    uncertain_references: set[str] = set()
    source_references: set[str] = set()
    payment_references: set[str] = set()
    for item in normalized.values():
        timeline_references = item["timeline_references"]
        evidence_references = item["evidence_references"]
        source_references.update(timeline_references)
        source_references.update(evidence_references)
        payment_references.add(item["payment_id"])
        if item["label"] == AttributionLabel.MALICIOUS.value:
            gross += item["amount_minor"]
            recoverable += item["amount_minor"] - item["reimbursed_minor"]
            contained += item["contained_minor"]
        elif item["label"] == AttributionLabel.LEGITIMATE.value:
            legitimate_disrupted += item["legitimate_value_disrupted_minor"]
        else:
            uncertain_references.update(timeline_references)
            uncertain_references.update(evidence_references)

    irreversible_loss = gross - recoverable
    remaining = recoverable - contained
    return FinancialExposure(
        tenant_id=tenant_id,
        case_id=case_id,
        currency=requested_currency,
        gross_exposure_minor=gross,
        recoverable_value_minor=recoverable,
        contained_value_minor=contained,
        legitimate_value_disrupted_minor=legitimate_disrupted,
        irreversible_loss_minor=irreversible_loss,
        remaining_exposure_minor=remaining,
        calculation_version=calculation_version,
        source_references=tuple(source_references),
        uncertain_source_references=tuple(uncertain_references),
        payment_references=tuple(payment_references),
    )


ExposureResult = FinancialExposure
calculate_financial_exposure = calculate_exposure


def _normalize_payment(
    value: object,
    *,
    index: int,
    tenant_id: str,
    case_id: str,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = value
        event_payload = payload.get("event_payload")
    else:
        event_payload = getattr(value, "event_payload", None)
        payload = event_payload if isinstance(event_payload, Mapping) else {}
        payload = {
            **payload,
            "tenant_id": getattr(value, "tenant_id", payload.get("tenant_id")),
            "case_id": getattr(value, "case_id", payload.get("case_id")),
            "timeline_event_id": getattr(
                value, "timeline_event_id", payload.get("timeline_event_id")
            ),
            "evidence_references": getattr(
                value, "evidence_references", payload.get("evidence_references", ())
            ),
        }
    nested = event_payload if isinstance(event_payload, Mapping) else {}

    def get(name: str, default: object = None) -> object:
        return payload.get(name, nested.get(name, default))

    actual_tenant = get("tenant_id")
    actual_case = get("case_id")
    if actual_tenant != tenant_id or actual_case != case_id:
        raise ExposureValidationError(f"payment {index} is outside the authorized case")
    payment_id = _required_text(get("payment_id"), f"payment {index} payment_id")
    timeline_event_id = _required_text(
        get("timeline_event_id"), f"payment {index} timeline_event_id"
    )
    state = get("payment_state", get("state"))
    if not isinstance(state, str) or state.strip().lower() != "captured":
        raise ExposureValidationError("only captured payments may enter exposure calculation")
    item_currency = _currency(get("currency"), allow_none=False)
    amount = _minor(get("amount_minor"), f"payment {index} amount_minor")
    source = _required_text(get("payment_source"), f"payment {index} payment_source")
    reimbursed = _minor(get("reimbursed_minor", 0), f"payment {index} reimbursed_minor")
    contained = _minor(get("contained_minor", 0), f"payment {index} contained_minor")
    disrupted = _minor(
        get("legitimate_value_disrupted_minor", 0),
        f"payment {index} legitimate_value_disrupted_minor",
    )
    if reimbursed > amount:
        raise ExposureValidationError("reimbursement exceeds payment amount")
    if amount > 0 and reimbursed == amount:
        raise ExposureValidationError("fully reimbursed payment is not an exposure input")
    if contained > amount - reimbursed:
        raise ExposureValidationError("contained value exceeds unreimbursed payment value")
    if disrupted > amount:
        raise ExposureValidationError("legitimate disruption exceeds payment amount")
    label = _label(get("attribution_label", get("label")), index)
    if source.strip().lower() in {
        "unknown",
        "unknown_source",
        "unavailable",
        "not_provided",
    }:
        raise ExposureValidationError("payment source is unknown")
    return {
        "payment_id": payment_id,
        "timeline_event_id": timeline_event_id,
        "timeline_references": {timeline_event_id},
        "evidence_references": set(_references(get("evidence_references", ()))),
        "tenant_id": actual_tenant,
        "case_id": actual_case,
        "amount_minor": amount,
        "currency": item_currency,
        "payment_source": source,
        "reimbursed_minor": reimbursed,
        "contained_minor": contained,
        "label": label,
        "legitimate_value_disrupted_minor": disrupted,
    }


def _same_payment_facts(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    fields = (
        "tenant_id",
        "case_id",
        "payment_id",
        "amount_minor",
        "currency",
        "payment_source",
        "reimbursed_minor",
        "contained_minor",
        "label",
        "legitimate_value_disrupted_minor",
    )
    return all(first[field] == second[field] for field in fields)


def _label(value: object, index: int) -> str:
    if isinstance(value, AttributionLabel):
        return value.value
    if not isinstance(value, str) or value.strip().lower() not in {
        label.value for label in AttributionLabel
    }:
        raise ExposureValidationError(f"payment {index} attribution label is unsupported")
    return value.strip().lower()


def _minor(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExposureValidationError(f"{name} must be a non-negative integer minor-unit value")
    return value


def _currency(value: object, *, allow_none: bool) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ExposureValidationError("currency must be an explicit three-letter ISO code")
    normalized = value.upper()
    return normalized


def _references(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise ExposureValidationError("source references must be a sequence")
    try:
        references = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ExposureValidationError("source references must be a sequence") from exc
    if any(not isinstance(reference, str) or not reference.strip() for reference in references):
        raise ExposureValidationError("source references contain an invalid value")
    return tuple(sorted(set(reference.strip() for reference in references)))


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExposureValidationError(f"{name} is required")
    return value.strip()


__all__ = [
    "ExposureResult",
    "ExposureValidationError",
    "FinancialExposure",
    "calculate_exposure",
    "calculate_financial_exposure",
]
