"""Authenticated incident intake HTTP routes."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import OIDCVerifier, RequiredRole, TenantAuthorizationError
from app.intake.service import IncidentIntakeService
from packages.contracts.intake import IncidentIntakeRequest, IncidentIntakeResponse


def create_intake_app(
    *,
    intake_service: IncidentIntakeService,
    oidc_verifier: OIDCVerifier,
    evidence_orchestrator: Any | None = None,
    timeline_reconstructor: Any | None = None,
) -> Any:
    """Build the intake API; later US1 stages are explicit, unused dependencies."""

    try:
        from fastapi import FastAPI
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared, not optional
        raise RuntimeError("FastAPI is required to construct the intake API") from exc

    app = FastAPI(title="RECLAIM Intake API")
    app.state.evidence_orchestrator = evidence_orchestrator
    app.state.timeline_reconstructor = timeline_reconstructor
    app.include_router(
        create_intake_router(
            intake_service=intake_service,
            oidc_verifier=oidc_verifier,
        )
    )
    return app


def create_intake_router(
    *,
    intake_service: IncidentIntakeService,
    oidc_verifier: OIDCVerifier,
) -> Any:
    """Create tenant-path intake routes with bearer-token authorization."""

    try:
        from fastapi import APIRouter, Header, HTTPException, status
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared, not optional
        raise RuntimeError("FastAPI is required to construct intake routes") from exc

    router = APIRouter()

    @router.post(
        "/tenants/{tenant_id}/incidents",
        response_model=IncidentIntakeResponse,
        status_code=status.HTTP_200_OK,
    )
    def intake_incident(
        tenant_id: str,
        request: IncidentIntakeRequest,
        authorization: str | None = Header(default=None),
    ) -> IncidentIntakeResponse:
        token = _bearer_token(authorization)
        try:
            context = oidc_verifier.authorize(
                token,
                tenant_id=tenant_id,
                required_role=RequiredRole.REVIEWER,
            )
            return intake_service.accept(request, authorization_context=context)
        except TenantAuthorizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated tenant or role is not authorized for intake",
            ) from exc

    return router


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        _raise_unauthorized()
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        _raise_unauthorized()
    return token.strip()


def _raise_unauthorized() -> None:
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="bearer authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
