"""Private authenticated agent service for fresh advisory analysis."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from packages.contracts.analysis_policy import ModelAnalysisRequest
from pydantic import BaseModel, ConfigDict, Field

from .fresh_run import AgentRunStatus, FreshAgentCoordinator
from .providers import ModelProvider

AGENT_SERVICE_VERSION = "agent-service-v1.0.0"
ServiceAuthorizer = Callable[[str], bool]


class AgentServiceRequest(BaseModel):
    """Strict request accepted by the private agent runner."""

    model_config = ConfigDict(extra="forbid")

    profile: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9.-]*$")
    request: ModelAnalysisRequest


def create_agent_service_app(
    *,
    provider: ModelProvider,
    service_authorizer: ServiceAuthorizer,
    configured_profile: str = "reclaim-specialist",
    action_environment: str = "simulator",
) -> Any:
    """Create an advisory-only service backed by a model-gateway client."""

    if not isinstance(provider, ModelProvider):
        raise TypeError("agent service requires a provider-neutral model-gateway client")
    if not callable(service_authorizer):
        raise TypeError("agent service authorizer is required")
    if action_environment not in {"simulator", "test_mode"}:
        raise ValueError("agent service cannot use the merchant-live action environment")

    from fastapi import FastAPI

    application = FastAPI(
        title="RECLAIM Advisory Agent",
        version=AGENT_SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    router = APIRouter()

    @router.post("/v1/agent/analyze")
    def analyze(
        body: AgentServiceRequest,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(authorization, service_authorizer)
        if body.profile != configured_profile:
            raise HTTPException(status_code=403, detail="agent profile is not authorized")
        try:
            run = FreshAgentCoordinator(
                provider,
                profile=body.profile,
                action_environment=action_environment,
            ).run(body.request)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="analysis request was rejected") from exc
        if run.status is AgentRunStatus.UNAVAILABLE:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif run.status is not AgentRunStatus.COMPLETED:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return run.to_dict()

    application.include_router(router)
    return application


def _authorize(authorization: str | None, service_authorizer: ServiceAuthorizer) -> None:
    if authorization is None:
        raise HTTPException(status_code=401, detail="service authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="service authentication is required")
    try:
        authorized = service_authorizer(token.strip())
    except Exception as exc:
        raise HTTPException(status_code=403, detail="service is not authorized") from exc
    if not authorized:
        raise HTTPException(status_code=403, detail="service is not authorized")


__all__ = ["AGENT_SERVICE_VERSION", "AgentServiceRequest", "create_agent_service_app"]
