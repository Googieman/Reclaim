"""Investigation proposals cannot become an execution or cross-tenant channel."""

from __future__ import annotations

import pytest

from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from workflows.activities.agent_analysis import AgentAnalysisActivityError, run_agent_analysis
from workflows.commands import CaseWorkflowCommand


def command() -> CaseWorkflowCommand:
    return CaseWorkflowCommand(
        tenant_id="tenant-temporal",
        case_id="case-temporal",
        correlation_id="correlation-temporal",
        command_id="command-temporal",
        stages=("rebuild_timeline", "analyze_case"),
    )


def context(tenant_id: str, identity_type: IdentityType = IdentityType.SERVICE):
    principal = AuthenticatedPrincipal(
        subject="worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=identity_type,
        issuer="test",
    )
    return principal.for_tenant(tenant_id)


def test_activity_rejects_remote_side_effects_from_investigation_runner() -> None:
    with pytest.raises(AgentAnalysisActivityError, match="remote side effects"):
        run_agent_analysis(
            command(),
            runner=lambda _command: {
                "tenant_id": "tenant-temporal",
                "case_id": "case-temporal",
                "execution_mode": "fresh_agent",
                "remote_side_effects": ["refund"],
            },
            authorization_context=context("tenant-temporal"),
        )


def test_activity_rejects_investigation_scope_or_identity_drift() -> None:
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
