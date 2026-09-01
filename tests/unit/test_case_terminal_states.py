"""T086 explicit case terminal-state contract tests."""

from __future__ import annotations

import pytest

from workflows.case_workflow import CaseWorkflowResult
from us3_test_seams import require_symbol


APPROVED_TERMINAL_STATES = (
    "verified_contained",
    "verified_failed",
    "escalated_unresolved",
)
GENERIC_TERMINAL_ALIASES = ("closed", "completed", "success")


@pytest.mark.parametrize("terminal_state", APPROVED_TERMINAL_STATES)
def test_only_approved_terminal_values_are_canonical(terminal_state: str) -> None:
    result = CaseWorkflowResult(
        tenant_id="tenant-us3-terminal",
        case_id="case-us3-terminal-001",
        workflow_id="workflow-us3-terminal-001",
        terminal_state=terminal_state,
        completed_stages=("verify_case",),
        recovered_count=0,
        authoritative_state=terminal_state,
    )

    assert result.terminal_state in APPROVED_TERMINAL_STATES
    assert result.terminal_state not in GENERIC_TERMINAL_ALIASES


def test_generic_terminal_aliases_are_not_approved_values() -> None:
    assert set(APPROVED_TERMINAL_STATES).isdisjoint(GENERIC_TERMINAL_ALIASES)
    assert "closed" not in APPROVED_TERMINAL_STATES
    assert "completed" not in APPROVED_TERMINAL_STATES
    assert "success" not in APPROVED_TERMINAL_STATES


def test_nonterminal_workflow_result_has_no_terminal_outcome() -> None:
    result = CaseWorkflowResult(
        tenant_id="tenant-us3-terminal",
        case_id="case-us3-terminal-001",
        workflow_id="workflow-us3-terminal-001",
        terminal_state=None,
        completed_stages=("evaluate_policy",),
        recovered_count=0,
        authoritative_state="action_pending",
    )

    assert result.terminal_state is None


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owner T098: explicit terminal-state transition implementation is absent",
)
def test_terminal_transition_rejects_generic_aliases_and_invalid_order() -> None:
    transition = require_symbol(
        "cases.terminal_states",
        "transition_case",
        task="T086 -> T098",
    )

    for terminal_state in APPROVED_TERMINAL_STATES:
        result = transition(
            current_state="containing",
            requested_state=terminal_state,
            tenant_id="tenant-us3-terminal",
            case_id="case-us3-terminal-001",
        )
        assert result.state == terminal_state
    for invalid_state in (*GENERIC_TERMINAL_ALIASES, "unknown-terminal"):
        with pytest.raises(ValueError):
            transition(
                current_state="containing",
                requested_state=invalid_state,
                tenant_id="tenant-us3-terminal",
                case_id="case-us3-terminal-001",
            )
