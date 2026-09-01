"""Deterministic, fail-closed rules attribution baseline."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion

from .models import AttributionInput, attribution_input_from_event

RULES_METHOD = "rules"
RULES_VERSION = "rules-v1.0.0"


class RulesAttributor:
    """Produce advisory attribution from a bounded set of known event facts.

    Evidence content is data, not instructions.  Unknown event types and malformed
    or incomplete known facts produce ``uncertain`` rather than a guessed label.
    """

    method = RULES_METHOD
    version = RULES_VERSION

    def attribute(
        self,
        event: object,
        *,
        tenant_id: str | None = None,
        case_id: str | None = None,
    ) -> AttributionSuggestion:
        attribution_input = (
            event if isinstance(event, AttributionInput) else attribution_input_from_event(event)
        )
        self._check_scope(attribution_input, tenant_id=tenant_id, case_id=case_id)
        return self._attribute_input(attribution_input)

    def attribute_record(
        self,
        event: object,
        *,
        tenant_id: str | None = None,
        case_id: str | None = None,
    ) -> object:
        """Return the suggestion with its tenant/case-bound input for persistence."""

        from .models import AttributionRecord

        attribution_input = (
            event if isinstance(event, AttributionInput) else attribution_input_from_event(event)
        )
        self._check_scope(attribution_input, tenant_id=tenant_id, case_id=case_id)
        return AttributionRecord(attribution_input, self._attribute_input(attribution_input))

    def _attribute_input(self, event: AttributionInput) -> AttributionSuggestion:
        references = event.evidence_references
        if event.uncertainty_reasons or event.conflicting_source_event_ids:
            reasons = list(event.uncertainty_reasons)
            if event.conflicting_source_event_ids:
                reasons.append("conflicting_sources")
            joined_reasons = ", ".join(sorted(set(reasons)))
            return _suggestion(
                event,
                AttributionLabel.UNCERTAIN,
                0.5,
                f"Authoritative evidence is uncertain ({joined_reasons}); "
                "human review is required.",
                references,
            )
        if not references:
            return _suggestion(
                event,
                AttributionLabel.UNCERTAIN,
                0.0,
                "No authoritative evidence reference is available for this event.",
                references,
            )

        payload = event.event_payload
        event_type = event.canonical_event_type
        try:
            if event_type == "payment.captured":
                return self._payment(event, payload)
            if event_type == "session.opened":
                return self._session(event, payload)
            if event_type == "profile.changed":
                return self._profile(event, payload)
            if event_type == "order.created":
                return self._order(event, payload)
        except _UnsupportedFact:
            pass

        return _suggestion(
            event,
            AttributionLabel.UNCERTAIN,
            0.0,
            f"The rules baseline does not support {event_type}; attribution remains uncertain.",
            references,
        )

    def _payment(
        self, event: AttributionInput, payload: Mapping[str, Any]
    ) -> AttributionSuggestion:
        signals = _payment_signals(payload)
        if signals is None:
            raise _UnsupportedFact
        new_device, profile_change, velocity, successful_orders = signals
        if new_device == 1 and profile_change == 1 and velocity >= 5 and successful_orders == 0:
            return _suggestion(
                event,
                AttributionLabel.MALICIOUS,
                0.96,
                "The payment matches a new device, recent profile change, and "
                "high session velocity with no established customer orders.",
                event.evidence_references,
            )
        if new_device == 0 and profile_change == 0 and velocity <= 1 and successful_orders >= 10:
            return _suggestion(
                event,
                AttributionLabel.LEGITIMATE,
                0.91,
                "The payment matches an established customer pattern without "
                "recent account changes.",
                event.evidence_references,
            )
        return _suggestion(
            event,
            AttributionLabel.UNCERTAIN,
            0.52,
            "The payment has some attribution signals but insufficient "
            "corroboration for certainty.",
            event.evidence_references,
        )

    def _session(
        self, event: AttributionInput, payload: Mapping[str, Any]
    ) -> AttributionSuggestion:
        new_device = _binary(payload.get("new_device"))
        velocity = _nonnegative_int(payload.get("session_velocity_5m"))
        successful_orders = _nonnegative_int(payload.get("successful_customer_orders"))
        if new_device is None or velocity is None or successful_orders is None:
            raise _UnsupportedFact
        if new_device == 1 and (velocity >= 5 or successful_orders == 0):
            return _suggestion(
                event,
                AttributionLabel.MALICIOUS,
                0.9,
                "The session combines a new device with high velocity or no "
                "established customer orders.",
                event.evidence_references,
            )
        if new_device == 0 and velocity <= 1 and successful_orders > 0:
            return _suggestion(
                event,
                AttributionLabel.LEGITIMATE,
                0.88,
                "The session matches an established device and customer pattern.",
                event.evidence_references,
            )
        return _suggestion(
            event,
            AttributionLabel.UNCERTAIN,
            0.5,
            "The session signals are insufficient to distinguish malicious from "
            "legitimate activity.",
            event.evidence_references,
        )

    def _profile(
        self, event: AttributionInput, payload: Mapping[str, Any]
    ) -> AttributionSuggestion:
        changed_by = payload.get("changed_by")
        change_type = payload.get("change_type")
        if not isinstance(changed_by, str) or not isinstance(change_type, str):
            raise _UnsupportedFact
        if changed_by.strip().lower() in {"unknown", "unknown_actor", "untrusted_actor"}:
            return _suggestion(
                event,
                AttributionLabel.MALICIOUS,
                0.94,
                "A sensitive profile change was attributed to an unknown actor.",
                event.evidence_references,
            )
        if changed_by.strip().lower() in {"customer", "self", "merchant_support"}:
            return _suggestion(
                event,
                AttributionLabel.LEGITIMATE,
                0.86,
                "The profile change has a recognized actor and no unsupported compromise signal.",
                event.evidence_references,
            )
        return _suggestion(
            event,
            AttributionLabel.UNCERTAIN,
            0.5,
            "The profile-change actor is not in the approved rules vocabulary.",
            event.evidence_references,
        )

    def _order(self, event: AttributionInput, payload: Mapping[str, Any]) -> AttributionSuggestion:
        state = payload.get("state")
        order_id = payload.get("order_id")
        if not isinstance(state, str) or not isinstance(order_id, str) or not order_id.strip():
            raise _UnsupportedFact
        if state.strip().lower() == "created":
            return _suggestion(
                event,
                AttributionLabel.LEGITIMATE,
                0.75,
                "The order is a valid created-order fact; untrusted order content "
                "is not treated as an instruction.",
                event.evidence_references,
            )
        return _suggestion(
            event,
            AttributionLabel.UNCERTAIN,
            0.5,
            "The order state is outside the deterministic rules baseline.",
            event.evidence_references,
        )

    @staticmethod
    def _check_scope(
        event: AttributionInput,
        *,
        tenant_id: str | None,
        case_id: str | None,
    ) -> None:
        if tenant_id is not None and tenant_id != event.tenant_id:
            raise ValueError("attribution input crosses tenant boundary")
        if case_id is not None and case_id != event.case_id:
            raise ValueError("attribution input crosses case boundary")


RulesBasedAttributor = RulesAttributor
RulesAttributionEngine = RulesAttributor


def attribute_timeline_event(
    event: object,
    *,
    tenant_id: str | None = None,
    case_id: str | None = None,
) -> AttributionSuggestion:
    return RulesAttributor().attribute(event, tenant_id=tenant_id, case_id=case_id)


def attribute_event(
    event: object,
    *,
    tenant_id: str | None = None,
    case_id: str | None = None,
) -> AttributionSuggestion:
    return attribute_timeline_event(event, tenant_id=tenant_id, case_id=case_id)


def _suggestion(
    event: AttributionInput,
    label: AttributionLabel,
    confidence: float,
    rationale: str,
    evidence_references: tuple[str, ...],
) -> AttributionSuggestion:
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("attribution confidence must be between 0 and 1")
    return AttributionSuggestion(
        timeline_event_id=event.timeline_event_id,
        label=label,
        confidence=confidence,
        rationale=rationale,
        evidence_references=evidence_references,
        method=RULES_METHOD,
        model_or_rules_version=RULES_VERSION,
    )


class _UnsupportedFact(Exception):
    pass


def _binary(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
        return None
    return value


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _payment_signals(payload: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    new_device = _binary(payload.get("new_device"))
    profile_change = _binary(payload.get("profile_change_24h"))
    velocity = _nonnegative_int(payload.get("session_velocity_5m"))
    successful_orders = _nonnegative_int(payload.get("successful_customer_orders"))
    if None in (new_device, profile_change, velocity, successful_orders):
        return None
    return new_device, profile_change, velocity, successful_orders  # type: ignore[return-value]


__all__ = [
    "RULES_METHOD",
    "RULES_VERSION",
    "RulesAttributor",
    "RulesAttributionEngine",
    "RulesBasedAttributor",
    "attribute_event",
    "attribute_timeline_event",
]
