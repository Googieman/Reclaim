"""Temporal activity for bounded fresh model analysis.

The injected runner owns model selection and typed parsing. This activity only
enforces service identity and workflow scope; it never executes a proposal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.commands import CaseWorkflowCommand

AgentAnalysisRunner = Callable[[CaseWorkflowCommand], Mapping[str, Any]]


class AgentAnalysisActivityError(RuntimeError):
    """Fresh analysis could not prove a bounded tenant-scoped result."""


@dataclass(frozen=True, slots=True)
class AgentAnalysisActivityDependencies:
    authorization_context_factory: Callable[[str], TenantAuthorizationContext]
    runner: AgentAnalysisRunner


def run_agent_analysis(
    command: CaseWorkflowCommand,
    *,
    runner: AgentAnalysisRunner,
    authorization_context: TenantAuthorizationContext,
) -> dict[str, Any]:
    if (
        authorization_context.tenant_id != command.tenant_id
        or authorization_context.identity_type is not IdentityType.SERVICE
    ):
        raise AgentAnalysisActivityError("agent analysis requires a tenant-bound service identity")
    try:
        value = runner(command)
    except Exception as exc:
        raise AgentAnalysisActivityError("fresh agent analysis failed") from exc
    if not isinstance(value, Mapping):
        raise AgentAnalysisActivityError("fresh agent runner returned an invalid result")
    result = dict(value)
    if result.get("tenant_id") != command.tenant_id or result.get("case_id") != command.case_id:
        raise AgentAnalysisActivityError("fresh agent result crossed tenant or case scope")
    if result.get("execution_mode") != "fresh_agent":
        raise AgentAnalysisActivityError("agent activity requires a fresh-agent result")
    if result.get("remote_side_effects") not in (None, [], ()):
        raise AgentAnalysisActivityError("agent analysis returned remote side effects")
    result.setdefault("authoritative", True)
    result.setdefault("state", "timeline_ready")
    return result


class AgentAnalysisActivities:
    def __init__(self, dependencies: AgentAnalysisActivityDependencies) -> None:
        self.dependencies = dependencies

    @activity.defn(name="case.analyze_case")
    async def analyze_case(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        context = self.dependencies.authorization_context_factory(command.tenant_id)
        try:
            return run_agent_analysis(
                command,
                runner=self.dependencies.runner,
                authorization_context=context,
            )
        except AgentAnalysisActivityError as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc


def make_agent_analysis_activities(
    dependencies: AgentAnalysisActivityDependencies,
) -> AgentAnalysisActivities:
    return AgentAnalysisActivities(dependencies)


__all__ = [
    "AgentAnalysisActivities",
    "AgentAnalysisActivityDependencies",
    "AgentAnalysisActivityError",
    "make_agent_analysis_activities",
    "run_agent_analysis",
]
