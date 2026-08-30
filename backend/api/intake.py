"""Authenticated incident intake HTTP routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.auth.oidc import OIDCVerifier, RequiredRole, TenantAuthorizationError
from app.config import get_settings
from app.intake.service import IncidentIntakeService, IntakePayloadTooLarge
from packages.contracts.intake import IncidentIntakeRequest, IncidentIntakeResponse


def create_intake_app(
    *,
    intake_service: IncidentIntakeService,
    oidc_verifier: OIDCVerifier,
    evidence_orchestrator: Any | None = None,
    timeline_reconstructor: Any | None = None,
    max_request_body_bytes: int | None = None,
) -> Any:
    """Build the intake API; later US1 stages are explicit, unused dependencies."""

    try:
        from fastapi import FastAPI
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared, not optional
        raise RuntimeError("FastAPI is required to construct the intake API") from exc

    app = FastAPI(title="RECLAIM Intake API")
    app.state.evidence_orchestrator = evidence_orchestrator
    app.state.timeline_reconstructor = timeline_reconstructor
    app.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_bytes=(
            get_settings().raw_object_max_bytes
            if max_request_body_bytes is None
            else max_request_body_bytes
        ),
    )
    app.include_router(
        create_intake_router(
            intake_service=intake_service,
            oidc_verifier=oidc_verifier,
        )
    )
    return app


class RequestBodySizeLimitMiddleware:
    """Reject an oversized HTTP body before FastAPI parses it."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("request body payload limit must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope.get("headers", ()))
        if content_length is not None and content_length > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive() -> dict[str, Any]:
            return messages.pop(0)

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        from starlette.responses import JSONResponse

        response = JSONResponse(
            {"detail": "request body exceeds configured size limit"},
            status_code=413,
        )
        await response(scope, receive, send)


def _content_length(headers: Any) -> int | None:
    for name, value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


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
        except IntakePayloadTooLarge as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="incident report exceeds configured size limit",
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
