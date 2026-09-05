"""Read-only demo mode availability API.

The endpoint exposes server-qualified mode facts.  It intentionally accepts no
provider state, credentials, or action command from the browser.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from replay.mode_selection import (
    ModeSelection,
    ModeSelectionError,
    select_mode_from_environment,
)


def create_demo_router(
    *,
    availability_provider: Callable[[], ModeSelection | Mapping[str, Any]] | None = None,
    oidc_verifier: Any | None = None,
) -> Any:
    """Build read-only mode routes for the demo and authenticated tenant scope."""

    try:
        from fastapi import APIRouter, Header, Query
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct demo routes") from exc

    router = APIRouter()

    @router.get("/demo/mode")
    def mode(
        requested_mode: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if oidc_verifier is not None:
            _authorize(oidc_verifier, authorization, None)
        return _mode_payload(requested_mode, availability_provider)

    @router.get("/tenants/{tenant_id}/demo/mode")
    def tenant_mode(
        tenant_id: str,
        requested_mode: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if oidc_verifier is not None:
            _authorize(oidc_verifier, authorization, tenant_id)
        payload = _mode_payload(requested_mode, availability_provider)
        payload["tenant_id"] = tenant_id
        return payload

    return router


def mode_status(*, requested_mode: str | None = None) -> dict[str, object]:
    """Return the environment-qualified mode for non-HTTP application wiring."""

    return select_mode_from_environment(requested_mode=requested_mode).to_dict()


def _mode_payload(
    requested_mode: str | None,
    availability_provider: Callable[[], ModeSelection | Mapping[str, Any]] | None,
) -> dict[str, Any]:
    try:
        selected = availability_provider() if availability_provider else None
        if selected is None:
            return dict(mode_status(requested_mode=requested_mode))
        if isinstance(selected, ModeSelection):
            return selected.to_dict()
        return dict(selected)
    except ModeSelectionError as exc:
        raise _http_error(422, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise _http_error(503, "mode availability is not qualified") from exc


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str | None) -> Any:
    from app.auth.oidc import RequiredRole
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        kwargs: dict[str, Any] = {"required_role": RequiredRole.REVIEWER}
        if tenant_id is not None:
            kwargs["tenant_id"] = tenant_id
        return oidc_verifier.authorize(token.strip(), **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=403, detail="demo mode access is not authorized") from exc


def _http_error(status_code: int, detail: str) -> Any:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail=detail)


build_demo_router = create_demo_router
create_mode_router = create_demo_router

__all__ = ["build_demo_router", "create_demo_router", "create_mode_router", "mode_status"]
