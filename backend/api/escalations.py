"""Authenticated escalation creation and optimistic resolution API."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import RequiredRole


def create_escalations_router(
    *, oidc_verifier: Any, service: Any, repository_factory: Any | None = None
) -> Any:
    try:
        from fastapi import APIRouter, Header, HTTPException
        from pydantic import BaseModel, ConfigDict, Field
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct escalation routes") from exc

    class EscalationBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        case_id: str = Field(min_length=1)
        owner_id: str = Field(min_length=1)
        reason: str = Field(min_length=1)
        remaining_exposure_minor: int = Field(ge=0)
        currency: str = Field(min_length=3, max_length=3)
        evidence_references: tuple[str, ...] = Field(min_length=1)
        recommended_human_decision: str = Field(min_length=1)
        canonical_action_id: str | None = None
        execution_id: str | None = None
        verification_id: str | None = None
        policy_version_id: str | None = None
        correlation_id: str | None = None

    class ResolveBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        escalation_id: str = Field(min_length=1)
        expected_version: int = Field(ge=0)

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/escalations")
    def create(
        tenant_id: str,
        body: EscalationBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.ESCALATION_OWNER)
        try:
            return service.create(
                tenant_id=context.tenant_id,
                case_id=body.case_id,
                owner_id=body.owner_id,
                owner_tenant_id=context.tenant_id,
                authorization_context=context,
                reason=body.reason,
                remaining_exposure_minor=body.remaining_exposure_minor,
                currency=body.currency,
                evidence_references=body.evidence_references,
                recommended_human_decision=body.recommended_human_decision,
                canonical_action_id=body.canonical_action_id,
                execution_id=body.execution_id,
                verification_id=body.verification_id,
                policy_version_id=body.policy_version_id,
                correlation_id=body.correlation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/tenants/{tenant_id}/escalations/{escalation_id}")
    def read(
        tenant_id: str,
        escalation_id: str,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        if repository_factory is None:
            raise HTTPException(status_code=500, detail="escalation reader is not configured")
        return repository_factory(context).get(escalation_id=escalation_id)

    @router.post("/tenants/{tenant_id}/escalations/resolve")
    def resolve(
        tenant_id: str,
        body: ResolveBody,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.ESCALATION_OWNER)
        if repository_factory is None:
            raise HTTPException(status_code=500, detail="escalation writer is not configured")
        try:
            return repository_factory(context).resolve(
                escalation_id=body.escalation_id, expected_version=body.expected_version
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
    except Exception as exc:
        raise HTTPException(status_code=403, detail="escalation authorization is required") from exc


__all__ = ["create_escalations_router"]
