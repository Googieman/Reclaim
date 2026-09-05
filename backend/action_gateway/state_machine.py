"""Explicit Action Gateway lifecycle transition authority."""

from __future__ import annotations

from packages.contracts.action_gateway import ActionExecutionState


class ActionGatewayStateError(ValueError):
    """Raised when a lifecycle transition would bypass a safety boundary."""


_ALLOWED: dict[ActionExecutionState, frozenset[ActionExecutionState]] = {
    ActionExecutionState.NOT_STARTED: frozenset({ActionExecutionState.RECEIVED}),
    ActionExecutionState.RECEIVED: frozenset({ActionExecutionState.VALIDATED}),
    ActionExecutionState.VALIDATED: frozenset(
        {ActionExecutionState.PENDING_REMOTE, ActionExecutionState.FAILED}
    ),
    ActionExecutionState.PENDING_REMOTE: frozenset(
        {
            ActionExecutionState.COMPLETED,
            ActionExecutionState.FAILED,
            ActionExecutionState.UNKNOWN,
        }
    ),
    ActionExecutionState.COMPLETED: frozenset({ActionExecutionState.VERIFYING}),
    ActionExecutionState.FAILED: frozenset({ActionExecutionState.VERIFYING}),
    ActionExecutionState.UNKNOWN: frozenset(
        {ActionExecutionState.RECONCILING, ActionExecutionState.ESCALATED}
    ),
    ActionExecutionState.RECONCILING: frozenset(
        {ActionExecutionState.RECONCILED, ActionExecutionState.ESCALATED}
    ),
    ActionExecutionState.RECONCILED: frozenset(
        {ActionExecutionState.PENDING_REMOTE, ActionExecutionState.VERIFYING}
    ),
    ActionExecutionState.VERIFYING: frozenset(
        {
            ActionExecutionState.VERIFIED_SUCCESS,
            ActionExecutionState.VERIFIED_FAILURE,
            ActionExecutionState.ESCALATED,
        }
    ),
    ActionExecutionState.VERIFIED_SUCCESS: frozenset(),
    ActionExecutionState.VERIFIED_FAILURE: frozenset(),
    ActionExecutionState.ESCALATED: frozenset(),
}


class ActionGatewayStateMachine:
    """Validate lifecycle transitions; it never performs a remote side effect."""

    @staticmethod
    def can_transition(current: ActionExecutionState, requested: ActionExecutionState) -> bool:
        return requested in _ALLOWED.get(current, frozenset())

    @classmethod
    def transition(
        cls, current: ActionExecutionState, requested: ActionExecutionState
    ) -> ActionExecutionState:
        if not cls.can_transition(current, requested):
            raise ActionGatewayStateError(
                f"invalid Action Gateway transition: {current.value} -> {requested.value}"
            )
        return requested


__all__ = ["ActionGatewayStateError", "ActionGatewayStateMachine"]
