"""Explicit terminal-state authority for the case containment lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

APPROVED_TERMINAL_STATES = frozenset(
    {"verified_contained", "verified_failed", "escalated_unresolved"}
)
FORBIDDEN_TERMINAL_ALIASES = frozenset({"closed", "completed", "success"})


class TerminalStateError(ValueError):
    """Raised when a case cannot claim an explicit terminal outcome."""


@dataclass(frozen=True, slots=True)
class TerminalTransition:
    tenant_id: str
    case_id: str
    state: str
    action_id: str | None = None
    execution_id: str | None = None
    verification_id: str | None = None
    escalation_id: str | None = None
    remaining_exposure_minor: int | None = None
    currency: str | None = None
    correlation_ids: tuple[str, ...] = ()
    audit_reference: str | None = None
    outbox_reference: str | None = None


def transition_case(
    *,
    current_state: str,
    requested_state: str,
    tenant_id: str,
    case_id: str,
    action_id: str | None = None,
    execution_id: str | None = None,
    verification_id: str | None = None,
    escalation_id: str | None = None,
    verification_result: str | None = None,
    required_actions_completed: bool | None = None,
    unresolved: bool | None = None,
    remaining_exposure_minor: int | None = None,
    currency: str | None = None,
    correlation_ids: Sequence[str] = (),
) -> TerminalTransition:
    """Validate an explicit terminal transition without performing I/O.

    Calls without lifecycle references are retained as a small enum-contract
    helper for T086.  The production ``CaseTerminalService`` always supplies
    verification/escalation evidence and therefore applies the stronger checks.
    """

    if requested_state not in APPROVED_TERMINAL_STATES:
        if requested_state in FORBIDDEN_TERMINAL_ALIASES:
            raise TerminalStateError("generic terminal aliases are forbidden")
        raise TerminalStateError("terminal state is unsupported")
    if not tenant_id.strip() or not case_id.strip():
        raise TerminalStateError("tenant and case identity are required")
    if current_state in APPROVED_TERMINAL_STATES:
        raise TerminalStateError("terminal case state is immutable")
    if current_state not in {"action_pending", "containing"}:
        raise TerminalStateError("case is not in the containment transition")
    references_present = any(
        value is not None
        for value in (action_id, execution_id, verification_id, escalation_id, verification_result)
    )
    if references_present:
        if requested_state == "verified_contained":
            if verification_result != "verified_success":
                raise TerminalStateError("containment requires verified-success evidence")
            if required_actions_completed is not True or unresolved is True:
                raise TerminalStateError("containment has unresolved or incomplete actions")
        elif requested_state == "verified_failed" and verification_result != "verified_failure":
            raise TerminalStateError("verified failure requires verified-failure evidence")
        elif requested_state == "escalated_unresolved" and not escalation_id:
            raise TerminalStateError("escalated terminal state requires escalation authority")
    if requested_state == "escalated_unresolved" and unresolved is False:
        raise TerminalStateError("resolved work cannot use the escalated terminal state")
    if remaining_exposure_minor is not None:
        if isinstance(remaining_exposure_minor, bool) or remaining_exposure_minor < 0:
            raise TerminalStateError("remaining exposure must be a non-negative integer")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise TerminalStateError("remaining exposure requires explicit currency")
        currency = currency.upper()
    return TerminalTransition(
        tenant_id=tenant_id,
        case_id=case_id,
        state=requested_state,
        action_id=action_id,
        execution_id=execution_id,
        verification_id=verification_id,
        escalation_id=escalation_id,
        remaining_exposure_minor=remaining_exposure_minor,
        currency=currency,
        correlation_ids=tuple(reference for reference in correlation_ids if reference),
    )


class CaseTerminalService:
    """Persist terminal state, audit, and outbox records in one UoW."""

    def __init__(self, *, unit_of_work: Any | None = None) -> None:
        self.unit_of_work = unit_of_work

    def transition(
        self, transition: TerminalTransition, *, owner: str | None = None
    ) -> TerminalTransition:
        if self.unit_of_work is None:
            return transition
        row = self.unit_of_work.cases.transition_terminal(
            case_id=transition.case_id,
            new_state=transition.state,
            escalation_owner=owner,
        )
        if str(row[0]) != transition.tenant_id or str(row[1]) != transition.case_id:
            raise TerminalStateError("persisted terminal case crossed tenant scope")
        from app.audit.actions import persist_action_audit
        from app.events.action_events import build_case_terminal_event

        audit = persist_action_audit(
            tenant_id=transition.tenant_id,
            case_id=transition.case_id,
            action_id=transition.action_id,
            execution_id=transition.execution_id,
            verification_id=transition.verification_id,
            escalation_id=transition.escalation_id,
            correlation_ids=transition.correlation_ids,
            outcome=transition.state,
            unit_of_work=self.unit_of_work,
        )
        event = build_case_terminal_event(transition, audit_reference=audit.audit_record.audit_id)
        self.unit_of_work.outbox.enqueue(outbox_id=f"outbox:{event.event_id}", event=event)
        return TerminalTransition(
            tenant_id=transition.tenant_id,
            case_id=transition.case_id,
            state=transition.state,
            action_id=transition.action_id,
            execution_id=transition.execution_id,
            verification_id=transition.verification_id,
            escalation_id=transition.escalation_id,
            remaining_exposure_minor=transition.remaining_exposure_minor,
            currency=transition.currency,
            correlation_ids=transition.correlation_ids,
            audit_reference=audit.audit_record.audit_id,
            outbox_reference=event.event_id,
        )


__all__ = [
    "APPROVED_TERMINAL_STATES",
    "CaseTerminalService",
    "FORBIDDEN_TERMINAL_ALIASES",
    "TerminalStateError",
    "TerminalTransition",
    "transition_case",
]
