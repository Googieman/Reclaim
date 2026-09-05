"""Authenticated approval request/decision routes."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import RequiredRole, TenantAuthorizationError
from approvals.service import ApprovalService
from pydantic import BaseModel, ConfigDict, Field


class ApprovalRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    target_resource: str = Field(min_length=1)
    policy_version_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    expected_version: int = 0


class ApprovalDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    expected_version: int | None = None


class ApprovalLifecycleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)
    expected_version: int | None = None


def create_approvals_router(
    *,
    oidc_verifier: Any,
    service: ApprovalService,
    on_decision: Any | None = None,
    request_resolver: Any | None = None,
) -> Any:
    try:
        from fastapi import APIRouter, Header, HTTPException
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct approval routes") from exc

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/approvals/request")
    def request(
        tenant_id: str,
        body: ApprovalRequestBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return service.request_approval(
                tenant_id=context.tenant_id,
                case_id=body.case_id,
                proposal_id=body.proposal_id,
                action_type=body.action_type,
                target_resource=body.target_resource,
                proposer_id=context.subject,
                policy_version_id=body.policy_version_id,
                correlation_id=body.correlation_id,
                requested_at=_now(),
                expected_version=body.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/approvals/approve")
    def approve(
        tenant_id: str,
        body: ApprovalDecisionBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.APPROVER)
        try:
            if request_resolver is not None:
                request_resolver(context.tenant_id, body.request_id)
            approval = service.approve(
                body.request_id,
                approver_context=context,
                expected_version=body.expected_version,
            )
            if on_decision is not None:
                on_decision(approval)
            return approval
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/approvals/reject")
    def reject(
        tenant_id: str,
        body: ApprovalDecisionBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.APPROVER)
        try:
            if request_resolver is not None:
                request_resolver(context.tenant_id, body.request_id)
            approval = service.reject(
                body.request_id,
                approver_context=context,
                expected_version=body.expected_version,
            )
            if on_decision is not None:
                on_decision(approval)
            return approval
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/approvals/expire")
    def expire(
        tenant_id: str,
        body: ApprovalLifecycleBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.APPROVER)
        try:
            return service.expire(
                body.approval_id,
                tenant_id=context.tenant_id,
                expected_version=body.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/approvals/revoke")
    def revoke(
        tenant_id: str,
        body: ApprovalLifecycleBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.APPROVER)
        try:
            return service.revoke(
                body.approval_id,
                tenant_id=context.tenant_id,
                expected_version=body.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _authorize(
    oidc_verifier: Any, authorization: str | None, tenant_id: str, role: RequiredRole
) -> Any:
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return oidc_verifier.authorize(token.strip(), tenant_id=tenant_id, required_role=role)
    except TenantAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="approval authorization is required") from exc


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


create_approval_router = create_approvals_router

__all__ = ["create_approval_router", "create_approvals_router"]
