"""Read-only authenticated audit projection API."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import RequiredRole


def create_audit_router(*, oidc_verifier: Any, repository_factory: Any) -> Any:
    try:
        from fastapi import APIRouter, Header, HTTPException
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct audit routes") from exc

    router = APIRouter()

    @router.get("/tenants/{tenant_id}/audit")
    def read_audit(
        tenant_id: str,
        case_id: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id)
        repository = repository_factory(context)
        reader = (
            getattr(repository, "for_case", None)
            if case_id
            else getattr(repository, "list_for_tenant", None)
        )
        if reader is None:
            raise HTTPException(status_code=500, detail="audit reader is not configured")
        try:
            return reader(case_id=case_id) if case_id else reader(tenant_id=context.tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
            token.strip(), tenant_id=tenant_id, required_role=RequiredRole.REVIEWER
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail="audit authorization is required") from exc


__all__ = ["create_audit_router"]
