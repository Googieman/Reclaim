"""Typed, authenticated control-plane boundary for containment commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from action_gateway.service import ActionGateway
from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext
from packages.contracts.action_gateway import ActionGatewayRequest, ActionGatewayResponse
from packages.contracts.analysis_policy import Approval, PolicyDecision


class ControlPlaneError(PermissionError):
    """Raised when a command cannot reach the isolated Action Gateway."""


def submit_action(
    *,
    request: ActionGatewayRequest,
    gateway: ActionGateway,
    policy_decision: PolicyDecision,
    authoritative_resource: object,
    authorization_context: TenantAuthorizationContext,
    gateway_authorization_context: TenantAuthorizationContext | None = None,
    approval: Approval | None = None,
    canonical_action_id: str | None = None,
    execution_store: Any | None = None,
) -> ActionGatewayResponse:
    """Submit only a typed, policy-bound request through the Action Gateway.

    The caller may be a reviewer, but the connector boundary must receive a
    separately authenticated service identity.  Resolvers and repositories are
    injected by application wiring; this function never accepts an arbitrary URL,
    connector method, SQL statement, or caller-supplied credential.
    """

    _require_scope(request.tenant_id, authorization_context)
    authorization_context.require_role(RequiredRole.REVIEWER)
    service_context = gateway_authorization_context or authorization_context
    if service_context.identity_type is not IdentityType.SERVICE:
        raise ControlPlaneError("Action Gateway service identity is required")
    _require_scope(request.tenant_id, service_context)
    try:
        return gateway.submit(
            request,
            policy_decision=policy_decision,
            approval=approval,
            authoritative_resource=authoritative_resource,
            authorization_context=service_context,
            canonical_action_id=canonical_action_id,
            execution_store=execution_store,
        )
    except Exception as exc:
        if isinstance(exc, ControlPlaneError):
            raise
        raise ControlPlaneError("typed action was rejected by the Action Gateway") from exc


@dataclass(frozen=True, slots=True)
class ControlPlaneDependencies:
    """Application-owned resolvers for policy, approval, and merchant state."""

    gateway: ActionGateway
    policy_resolver: Callable[[TenantAuthorizationContext, ActionGatewayRequest], PolicyDecision]
    resource_resolver: Callable[[TenantAuthorizationContext, ActionGatewayRequest], object]
    approval_resolver: Callable[[TenantAuthorizationContext, ActionGatewayRequest], Approval | None]
    gateway_authorization_context: TenantAuthorizationContext | None = None
    execution_store: Any | None = None
    execution_repository_factory: Callable[[TenantAuthorizationContext], Any] | None = None


def create_control_plane_router(
    *, oidc_verifier: Any, dependencies: ControlPlaneDependencies
) -> Any:
    """Build the narrow HTTP surface; all mutation work remains in ``submit_action``."""

    try:
        from fastapi import APIRouter, Header, HTTPException
        from pydantic import BaseModel, ConfigDict, Field
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct control-plane routes") from exc

    class ActionBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        case_id: str = Field(min_length=1)
        proposal_id: str = Field(min_length=1)
        action_type: str = Field(min_length=1)
        connector_id: str = Field(min_length=1)
        operation: str = Field(min_length=1)
        target_resource: str = Field(min_length=1)
        parameters: dict[str, Any] = Field(default_factory=dict)
        policy_decision_id: str = Field(min_length=1)
        policy_version_id: str = Field(min_length=1)
        approval_id: str | None = None
        idempotency_key: str = Field(min_length=1)
        causation_id: str = Field(min_length=1)
        request_checksum: str = Field(min_length=1)
        requested_at: Any

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/actions")
    def submit(
        tenant_id: str,
        body: ActionBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        try:
            request = ActionGatewayRequest.model_validate(body.model_dump())
            decision = dependencies.policy_resolver(context, request)
            resource = dependencies.resource_resolver(context, request)
            approval = dependencies.approval_resolver(context, request)
            return submit_action(
                request=request,
                gateway=dependencies.gateway,
                policy_decision=decision,
                authoritative_resource=resource,
                authorization_context=context,
                gateway_authorization_context=dependencies.gateway_authorization_context,
                approval=approval,
                execution_store=dependencies.execution_store,
            )
        except (ValueError, ControlPlaneError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/tenants/{tenant_id}/actions/{execution_id}")
    def status(
        tenant_id: str,
        execution_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        if dependencies.execution_repository_factory is None:
            raise HTTPException(status_code=500, detail="action status reader is not configured")
        return dependencies.execution_repository_factory(context).get(execution_id=execution_id)

    return router


def _require_scope(tenant_id: str, context: TenantAuthorizationContext) -> None:
    if context.tenant_id != tenant_id:
        raise ControlPlaneError("command crosses authenticated tenant scope")


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return oidc_verifier.authorize(
            token.strip(), tenant_id=tenant_id, required_role=RequiredRole.REVIEWER
        )
    except Exception as exc:
        raise HTTPException(
            status_code=403, detail="action submission authorization is required"
        ) from exc


__all__ = [
    "ControlPlaneDependencies",
    "ControlPlaneError",
    "create_control_plane_router",
    "submit_action",
]
