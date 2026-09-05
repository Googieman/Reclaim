"""Read-only, explicitly replay-labelled API boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from replay.runner import ReplayRunner, run_replay


class ReplayBody(BaseModel):
    """Strict, side-effect-free replay request."""

    model_config = ConfigDict(extra="forbid")
    fixture_version: str = Field(default="canonical-v1.0.0", min_length=1)
    case_id: str = Field(min_length=1)
    correlation_id: str | None = None
    policy_version_id: str = Field(default="policy-v1.0.0", min_length=1)
    model_provider_mode: str = Field(default="replay-fixture/provider-v1.0.0", min_length=1)
    deterministic_seed: str | int = 0
    environment_metadata: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] | None = None


def replay_case(
    payload: dict[str, Any],
    *,
    runner: ReplayRunner | None = None,
    tenant_id: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Run one replay request without accepting credentials or mutation commands."""

    values = dict(payload)
    values.pop("mode", None)
    values.pop("label", None)
    if tenant_id is not None:
        values["tenant_id"] = tenant_id
    if case_id is not None:
        values["case_id"] = case_id
    return (runner or ReplayRunner()).run(mode="replay", **values)


def create_replay_router(
    *, runner: ReplayRunner | None = None, oidc_verifier: Any | None = None
) -> Any:
    """Build the narrow FastAPI replay surface.

    When an OIDC verifier is supplied, a reviewer token is required for the
    tenant-scoped read.  The endpoint never accepts a provider credential or an
    Action Gateway dependency.
    """

    try:
        from fastapi import APIRouter, Header, HTTPException
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to construct replay routes") from exc

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/cases/{case_id}/replay")
    def replay(
        tenant_id: str,
        case_id: str,
        body: ReplayBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if body.case_id != case_id:
            raise HTTPException(status_code=422, detail="case scope does not match replay body")
        if oidc_verifier is not None:
            _authorize(oidc_verifier, authorization, tenant_id)
        try:
            return replay_case(
                body.model_dump(exclude_none=True),
                runner=runner,
                tenant_id=tenant_id,
                case_id=case_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/replay")
    def replay_unscoped(
        body: ReplayBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if oidc_verifier is not None:
            raise HTTPException(status_code=400, detail="tenant-scoped replay route is required")
        try:
            return replay_case(body.model_dump(exclude_none=True), runner=runner)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    from app.auth.oidc import RequiredRole

    if authorization is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        return oidc_verifier.authorize(
            token.strip(), tenant_id=tenant_id, required_role=RequiredRole.REVIEWER
        )
    except Exception as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="replay authorization is required") from exc


build_replay_router = create_replay_router

__all__ = ["build_replay_router", "create_replay_router", "replay_case", "run_replay"]
