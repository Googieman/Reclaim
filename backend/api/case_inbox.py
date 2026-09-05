"""Authenticated cursor-paginated operator case inbox routes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.auth.oidc import RequiredRole, TenantAuthorizationError
from app.cases.inbox import CaseInboxError, CaseInboxService
from fastapi import HTTPException
from packages.contracts.case_inbox import CaseInboxPage


def create_case_inbox_router(*, service: CaseInboxService, oidc_verifier: Any) -> Any:
    from fastapi import APIRouter, Header, Query, status

    router = APIRouter()

    @router.get(
        "/tenants/{tenant_id}/cases",
        response_model=CaseInboxPage,
        status_code=status.HTTP_200_OK,
    )
    def list_cases(
        tenant_id: str,
        state: str | None = Query(default=None, min_length=1),
        automation_status: str | None = Query(default=None, min_length=1),
        q: str | None = Query(default=None, max_length=100),
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
        authorization: str | None = Header(default=None),
        x_correlation_id: str | None = Header(default=None),
    ) -> CaseInboxPage:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return service.list_cases(
                authorization_context=context,
                correlation_id=x_correlation_id or f"case-inbox:{uuid4().hex}",
                state=state,
                automation_status=automation_status,
                query=q,
                limit=limit,
                cursor=cursor,
            )
        except CaseInboxError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def _authorize(
    verifier: Any,
    authorization: str | None,
    tenant_id: str,
    role: RequiredRole,
) -> Any:
    token = _bearer(authorization)
    try:
        return verifier.authorize(token, tenant_id=tenant_id, required_role=role)
    except TenantAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="case inbox access is not authorized") from exc


def _bearer(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="bearer authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    return token.strip()


__all__ = ["create_case_inbox_router"]
