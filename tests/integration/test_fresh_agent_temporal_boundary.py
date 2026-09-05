"""The optional Temporal activity preserves service and case boundaries."""

from __future__ import annotations

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from workflows.activities.agent_analysis import (
    AgentAnalysisActivityError,
    run_agent_analysis,
)
from workflows.commands import CaseWorkflowCommand


def context(tenant_id: str, identity_type: IdentityType = IdentityType.SERVICE):
    principal = AuthenticatedPrincipal(
        subject="worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=identity_type,
        issuer="test",
    )
    return principal.for_tenant(tenant_id)


def command() -> CaseWorkflowCommand:
    return CaseWorkflowCommand(
        tenant_id="tenant-temporal",
        case_id="case-temporal",
        correlation_id="correlation-temporal",
        command_id="command-temporal",
        stages=("rebuild_timeline", "analyze_case"),
    )


def test_agent_activity_accepts_only_service_scoped_fresh_result() -> None:
    result = run_agent_analysis(
        command(),
        runner=lambda _command: {
            "tenant_id": "tenant-temporal",
            "case_id": "case-temporal",
            "execution_mode": "fresh_agent",
            "remote_side_effects": [],
        },
        authorization_context=context("tenant-temporal"),
    )
    assert result["authoritative"] is True
    assert result["state"] == "timeline_ready"


def test_agent_activity_rejects_wrong_identity_or_scope() -> None:
    with pytest.raises(AgentAnalysisActivityError, match="service identity"):
        run_agent_analysis(
            command(),
            runner=lambda _command: {
                "tenant_id": "tenant-temporal",
                "case_id": "case-temporal",
                "execution_mode": "fresh_agent",
            },
            authorization_context=context("tenant-temporal", IdentityType.USER),
        )
    with pytest.raises(AgentAnalysisActivityError, match="scope"):
        run_agent_analysis(
            command(),
            runner=lambda _command: {
                "tenant_id": "tenant-other",
                "case_id": "case-temporal",
                "execution_mode": "fresh_agent",
            },
            authorization_context=context("tenant-temporal"),
        )
