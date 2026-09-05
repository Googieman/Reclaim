"""Temporal containment activity: orchestration only, PostgreSQL remains truth."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.commands import CaseWorkflowCommand

CONTAINMENT_STAGE_ORDER = (
    "typed_proposal",
    "policy_evaluation",
    "approval",
    "canonical_action",
    "action_gateway",
    "execution_persistence",
    "unknown_reconciliation",
    "merchant_verification",
    "escalation",
    "terminal_transition",
)


class ContainmentActivityError(RuntimeError):
    """Raised when a containment activity cannot prove authoritative progress."""


ContainmentRunner = Callable[[CaseWorkflowCommand], Mapping[str, Any]]
ContainmentStep = Callable[[CaseWorkflowCommand, Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ContainmentActivityDependencies:
    authorization_context_factory: Callable[[str], TenantAuthorizationContext]
    runner: ContainmentRunner


@dataclass(frozen=True, slots=True)
class ContainmentRun:
    tenant_id: str
    case_id: str
    state: str
    authoritative: bool
    completed_stages: tuple[str, ...]
    terminal_state: str | None = None


@dataclass(frozen=True, slots=True)
class ContainmentPipeline:
    """Typed application pipeline injected into the Temporal activity.

    Each step receives only the command and prior typed results.  The worker
    supplies steps that read/write PostgreSQL through the existing policy,
    approval, gateway, verification, escalation, and terminal services.
    """

    steps: Mapping[str, ContainmentStep]

    def __call__(self, command: CaseWorkflowCommand) -> Mapping[str, Any]:
        state: dict[str, Any] = {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "authoritative": True,
        }
        completed: list[str] = []
        for stage in CONTAINMENT_STAGE_ORDER:
            step = self.steps.get(stage)
            if step is None:
                raise ContainmentActivityError(
                    f"containment pipeline is missing required stage {stage}"
                )
            result = step(command, dict(state))
            if not isinstance(result, Mapping):
                raise ContainmentActivityError(
                    f"containment stage {stage} returned an invalid result"
                )
            state.update(result)
            completed.append(stage)
            state["completed_stages"] = tuple(completed)
        return state


def run_containment(
    command: CaseWorkflowCommand,
    *,
    runner: ContainmentRunner,
    authorization_context: TenantAuthorizationContext,
) -> dict[str, Any]:
    """Run the injected typed pipeline and require its Postgres authority proof."""

    if (
        authorization_context.tenant_id != command.tenant_id
        or authorization_context.identity_type is not IdentityType.SERVICE
    ):
        raise ContainmentActivityError("containment requires a tenant-bound service identity")
    try:
        value = runner(command)
    except Exception as exc:
        raise ContainmentActivityError("containment pipeline failed") from exc
    if not isinstance(value, Mapping):
        raise ContainmentActivityError("containment pipeline returned an invalid result")
    result = dict(value)
    if result.get("tenant_id") != command.tenant_id or result.get("case_id") != command.case_id:
        raise ContainmentActivityError("containment result crossed tenant or case scope")
    if result.get("authoritative") is not True:
        raise ContainmentActivityError("containment must confirm PostgreSQL authority")
    completed = tuple(result.get("completed_stages", ()))
    if any(stage not in CONTAINMENT_STAGE_ORDER for stage in completed):
        raise ContainmentActivityError("containment returned an unknown stage")
    positions = tuple(CONTAINMENT_STAGE_ORDER.index(stage) for stage in completed)
    if positions != tuple(sorted(positions)) or len(set(completed)) != len(completed):
        raise ContainmentActivityError("containment stages are out of order or repeated")
    if "terminal_state" in result and result["terminal_state"] not in {
        None,
        "verified_contained",
        "verified_failed",
        "escalated_unresolved",
    }:
        raise ContainmentActivityError("containment terminal state is unsupported")
    return result


class ContainmentActivities:
    """Durable activity wrapper around application-owned containment wiring."""

    def __init__(self, dependencies: ContainmentActivityDependencies) -> None:
        self.dependencies = dependencies

    @activity.defn(name="case.run_containment")
    async def run_containment_activity(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        context = self.dependencies.authorization_context_factory(command.tenant_id)
        try:
            return run_containment(
                command,
                runner=self.dependencies.runner,
                authorization_context=context,
            )
        except ContainmentActivityError as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc


def make_containment_activities(
    dependencies: ContainmentActivityDependencies,
) -> ContainmentActivities:
    return ContainmentActivities(dependencies)


__all__ = [
    "CONTAINMENT_STAGE_ORDER",
    "ContainmentActivityDependencies",
    "ContainmentActivityError",
    "ContainmentActivities",
    "ContainmentPipeline",
    "ContainmentRun",
    "make_containment_activities",
    "run_containment",
]
