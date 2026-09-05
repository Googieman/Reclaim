"""Authenticated documentation help endpoint."""

from __future__ import annotations

from typing import Any

from app.auth.oidc import RequiredRole
from app.help_chat.service import HelpChatService
from fastapi import APIRouter, Header, HTTPException, status
from packages.contracts.help_chat import HelpChatRequest, HelpChatResponse


def create_help_chat_router(*, service: HelpChatService, oidc_verifier: Any) -> APIRouter:
    if not isinstance(service, HelpChatService):
        raise TypeError("help chat service is required")
    if oidc_verifier is None:
        raise ValueError("help chat requires a verified identity implementation")

    router = APIRouter()

    @router.post("/help/chat", response_model=HelpChatResponse)
    def chat(
        body: HelpChatRequest,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> HelpChatResponse:
        _authorize(oidc_verifier, authorization, tenant_id)
        if body.case_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="case-aware help is not enabled",
            )
        return service.answer(body.question, case_id=None)

    return router


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str | None) -> Any:
    if authorization is None or tenant_id is None or not tenant_id.strip():
        raise HTTPException(
            status_code=401,
            detail="bearer authentication and tenant scope are required",
        )
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return oidc_verifier.authorize(
            token.strip(), tenant_id=tenant_id, required_role=RequiredRole.REVIEWER
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail="help access is not authorized") from exc


__all__ = ["create_help_chat_router"]
