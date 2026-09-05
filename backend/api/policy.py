"""Authenticated policy publication API; no request body establishes authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.auth.oidc import RequiredRole, TenantAuthorizationError
from policy.change_control import PolicyChange, PolicyChangeController
from policy.versions import build_policy_version


def create_policy_router(
    *, oidc_verifier: Any, controller: PolicyChangeController | None = None
) -> Any:
    try:
        from fastapi import APIRouter, Header, HTTPException, status
        from pydantic import BaseModel, ConfigDict, Field
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct policy routes") from exc

    class PolicyChangeBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        change: str = Field(min_length=1)
        thresholds: dict[str, Any]
        action_allowlist: tuple[str, ...] = ()

    class PolicySubmitBody(PolicyChangeBody):
        policy_version_id: str = Field(min_length=1)
        change_id: str = Field(min_length=1)
        base_policy_version_id: str | None = None
        approval_rules: dict[str, Any] = Field(default_factory=dict)
        effective_from: datetime
        effective_to: datetime | None = None

    router = APIRouter()
    change_controller = controller or PolicyChangeController()

    @router.post("/tenants/{tenant_id}/policies/validate")
    def validate(
        tenant_id: str,
        body: PolicyChangeBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        result = change_controller.validate(
            tenant_id=context.tenant_id,
            change=body.change,
            thresholds=body.thresholds,
            action_allowlist=body.action_allowlist,
            authorization_context=context,
        )
        if not result.accepted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason)
        return result

    @router.post("/tenants/{tenant_id}/policies/changes")
    def submit(
        tenant_id: str,
        body: PolicySubmitBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        validation = change_controller.validate(
            tenant_id=context.tenant_id,
            change=body.change,
            thresholds=body.thresholds,
            action_allowlist=body.action_allowlist,
            authorization_context=context,
        )
        if not validation.accepted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=validation.reason)
        try:
            policy = build_policy_version(
                policy_version_id=body.policy_version_id,
                tenant_id=context.tenant_id,
                thresholds=validation.thresholds,
                action_allowlist=validation.action_allowlist,
                approval_rules=body.approval_rules,
                effective_from=body.effective_from,
                effective_to=body.effective_to,
                author=context.subject,
            )
            change = change_controller.submit(
                PolicyChange(
                    change_id=body.change_id,
                    tenant_id=context.tenant_id,
                    base_policy_version_id=body.base_policy_version_id,
                    proposed_policy_version=policy,
                    requested_by=context.subject,
                    requested_at=datetime.now(UTC),
                ),
                expected_base_version_id=body.base_policy_version_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return change

    @router.post("/tenants/{tenant_id}/policies/changes/{change_id}/publish")
    def publish(
        tenant_id: str,
        change_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        change = change_controller.get(tenant_id=context.tenant_id, change_id=change_id)
        if change is None:
            raise HTTPException(status_code=404, detail="policy change was not found")
        result = change_controller.publish(change, authorization_context=context)
        if not result.accepted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason)
        return result

    return router


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return oidc_verifier.authorize(
            token.strip(), tenant_id=tenant_id, required_role=RequiredRole.POLICY_OWNER
        )
    except TenantAuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="policy-owner authorization is required"
        ) from exc


__all__ = ["create_policy_router"]
