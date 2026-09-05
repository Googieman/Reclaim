"""Authenticated RECLAIM APIs used by the n8n workflow boundary."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationError
from app.orchestration.service import (
    OrchestrationResponse,
    OrchestrationService,
    OrchestrationServiceError,
)
from fastapi import HTTPException
from packages.contracts.case_inbox import OrchestrationStage
from packages.contracts.orchestration import (
    NormalizedIntakeResponse,
    OrchestrationRecoveryRequest,
    OrchestrationRunResponse,
    OrchestrationStageRequest,
    StartOrchestrationRunRequest,
)
from pydantic import BaseModel, ConfigDict, Field


class OrchestrationClaimRequest(BaseModel):
    """Strict internal claim body; n8n cannot smuggle arbitrary commands."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_state: str = Field(min_length=1)
    external_execution_id: str = Field(min_length=1, max_length=256)


def create_orchestration_router(*, service: OrchestrationService, oidc_verifier: Any) -> Any:
    from fastapi import APIRouter, Header, status

    router = APIRouter()

    @router.post(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/runs",
        response_model=OrchestrationRunResponse,
        status_code=status.HTTP_200_OK,
    )
    def start_run(
        tenant_id: str,
        case_id: str,
        body: StartOrchestrationRunRequest,
        authorization: str | None = Header(default=None),
    ) -> OrchestrationRunResponse:
        context = _authorize_start(oidc_verifier, authorization, tenant_id)
        try:
            return _as_contract(
                service.start_run(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    request=body,
                    authorization_context=context,
                )
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/runs/{run_id}/claim",
        response_model=OrchestrationRunResponse,
        status_code=status.HTTP_200_OK,
    )
    def claim_run(
        tenant_id: str,
        case_id: str,
        run_id: str,
        body: OrchestrationClaimRequest,
        authorization: str | None = Header(default=None),
    ) -> OrchestrationRunResponse:
        context = _authorize_service(oidc_verifier, authorization, tenant_id)
        execution_id = body.external_execution_id
        try:
            return _as_contract(
                service.claim_run(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    run_id=run_id,
                    expected_state=body.expected_state,
                    external_execution_id=execution_id,
                    authorization_context=context,
                )
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/recovery",
        response_model=OrchestrationRunResponse,
        status_code=status.HTTP_200_OK,
    )
    def recover(
        tenant_id: str,
        case_id: str,
        body: OrchestrationRecoveryRequest,
        authorization: str | None = Header(default=None),
    ) -> OrchestrationRunResponse:
        context = _authorize_service(oidc_verifier, authorization, tenant_id)
        try:
            return _as_contract(
                service.recover(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    request=body,
                    authorization_context=context,
                )
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/runs/{run_id}/normalize-intake",
        response_model=NormalizedIntakeResponse,
        status_code=status.HTTP_200_OK,
    )
    def normalize_intake(
        tenant_id: str,
        case_id: str,
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> NormalizedIntakeResponse:
        context = _authorize_service(oidc_verifier, authorization, tenant_id)
        try:
            return service.normalize_intake(
                tenant_id=tenant_id,
                case_id=case_id,
                run_id=run_id,
                authorization_context=context,
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/runs/{run_id}/stages/{stage}",
        response_model=OrchestrationRunResponse,
        status_code=status.HTTP_200_OK,
    )
    def record_stage(
        tenant_id: str,
        case_id: str,
        run_id: str,
        stage: str,
        body: OrchestrationStageRequest,
        authorization: str | None = Header(default=None),
    ) -> OrchestrationRunResponse:
        context = _authorize_service(oidc_verifier, authorization, tenant_id)
        try:
            allowlisted_stage = OrchestrationStage(stage)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="orchestration stage is not allowlisted"
            ) from exc
        try:
            return _as_contract(
                service.record_stage(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    run_id=run_id,
                    stage=allowlisted_stage,
                    request=body,
                    authorization_context=context,
                )
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/tenants/{tenant_id}/cases/{case_id}/orchestration/runs/{run_id}",
        response_model=OrchestrationRunResponse,
    )
    def read_run(
        tenant_id: str,
        case_id: str,
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> OrchestrationRunResponse:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        try:
            return _as_contract(
                service.get_run(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    run_id=run_id,
                    authorization_context=context,
                )
            )
        except OrchestrationServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def _as_contract(value: OrchestrationResponse) -> OrchestrationRunResponse:
    return OrchestrationRunResponse(
        tenant_id=value.tenant_id,
        case_id=value.case_id,
        run_id=value.run_id,
        workflow_version=value.workflow_version,
        external_execution_id=value.external_execution_id,
        stage=value.stage,
        status=value.status,
        failure_code=value.failure_code,
    )


def _authorize_start(verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    token = _bearer(authorization)
    try:
        context = verifier.authorize(token, tenant_id=tenant_id)
    except TenantAuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="orchestration access is not authorized"
        ) from exc
    if context.identity_type is IdentityType.SERVICE:
        return context
    try:
        context.require_role(RequiredRole.REVIEWER)
    except TenantAuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="orchestration access is not authorized"
        ) from exc
    return context


def _authorize_service(verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    token = _bearer(authorization)
    try:
        context = verifier.authorize(token, tenant_id=tenant_id)
    except TenantAuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="orchestration service is not authorized"
        ) from exc
    if (
        context.identity_type is not IdentityType.SERVICE
        or RequiredRole.ORCHESTRATOR.value not in context.roles
    ):
        raise HTTPException(status_code=403, detail="orchestration service is not authorized")
    return context


def _authorize(verifier: Any, authorization: str | None, tenant_id: str, role: RequiredRole) -> Any:
    token = _bearer(authorization)
    try:
        return verifier.authorize(token, tenant_id=tenant_id, required_role=role)
    except TenantAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="orchestration read is not authorized") from exc


def _bearer(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    return token.strip()


__all__ = ["create_orchestration_router"]
