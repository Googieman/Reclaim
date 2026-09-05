"""Authenticated, provider-owning model transport boundary.

The model gateway is the only service that resolves an installed provider profile.
Callers submit a typed redacted analysis request; they cannot choose a vendor model,
endpoint, API key, or arbitrary LiteLLM transport option.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from agent.providers import (
    ModelCompletion,
    ModelProvider,
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderUnavailable,
    ProviderMetadata,
)
from agent.tools import ToolResult
from fastapi import APIRouter, Header, HTTPException, Response, status
from packages.contracts.analysis_policy import ModelAnalysisRequest
from pydantic import BaseModel, ConfigDict, Field

MODEL_GATEWAY_VERSION = "model-gateway-v1.0.0"
ServiceAuthorizer = Callable[[str], bool]


class ToolResultEnvelope(BaseModel):
    """Strict wire representation of a side-effect-free tool result."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    schema_version: str = Field(min_length=1)

    def to_domain(self) -> ToolResult:
        return ToolResult(**self.model_dump())


class ModelGatewayRequest(BaseModel):
    """Only the request data permitted across the private model boundary."""

    model_config = ConfigDict(extra="forbid")

    profile: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9.-]*$")
    request: ModelAnalysisRequest
    tool_results: tuple[ToolResultEnvelope, ...] = ()


class ModelGatewayResponse(BaseModel):
    """Provider-neutral response used only between private services."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any]
    raw_output: Any
    tool_calls: tuple[dict[str, Any], ...] = ()
    token_count: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)

    @classmethod
    def from_completion(cls, completion: ModelCompletion) -> ModelGatewayResponse:
        return cls(
            metadata={
                "provider": completion.metadata.provider,
                "model": completion.metadata.model,
                "mode": completion.metadata.mode.value,
                "request_schema_version": completion.metadata.request_schema_version,
                "response_schema_version": completion.metadata.response_schema_version,
                "adapter_version": completion.metadata.adapter_version,
            },
            raw_output=completion.raw_output,
            tool_calls=tuple(
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": dict(call.arguments),
                    "schema_version": call.schema_version,
                }
                for call in completion.tool_calls
            ),
            token_count=completion.token_count,
            estimated_cost=completion.estimated_cost,
        )

    def to_completion(self) -> ModelCompletion:
        try:
            metadata = ProviderMetadata(**self.metadata)
            from agent.tools import ToolCall

            calls = tuple(ToolCall(**call) for call in self.tool_calls)
            return ModelCompletion(
                metadata=metadata,
                raw_output=self.raw_output,
                tool_calls=calls,
                token_count=self.token_count,
                estimated_cost=self.estimated_cost,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelProviderResponseError("model gateway response is malformed") from exc


class ModelGatewayClient:
    """Provider-neutral client consumed by the agent service."""

    def __init__(
        self,
        sender: Callable[[ModelGatewayRequest], ModelGatewayResponse | Mapping[str, Any]],
        *,
        profile: str,
        metadata: ProviderMetadata,
    ) -> None:
        if not callable(sender):
            raise TypeError("model gateway sender is required")
        if not profile.strip():
            raise ValueError("model gateway profile is required")
        if not isinstance(metadata, ProviderMetadata):
            raise TypeError("model gateway metadata is required")
        self._sender = sender
        self._profile = profile
        self._metadata = metadata

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion:
        payload = ModelGatewayRequest(
            profile=self._profile,
            request=request,
            tool_results=tuple(
                ToolResultEnvelope(
                    call_id=result.call_id,
                    name=result.name,
                    tenant_id=result.tenant_id,
                    case_id=result.case_id,
                    ok=result.ok,
                    output=dict(result.output),
                    error=result.error,
                    schema_version=result.schema_version,
                )
                for result in tool_results
            ),
        )
        try:
            received = self._sender(payload)
            response = (
                received
                if isinstance(received, ModelGatewayResponse)
                else ModelGatewayResponse.model_validate(received)
            )
            completion = response.to_completion()
        except ModelProviderError:
            raise
        except Exception as exc:
            raise ModelProviderUnavailable("model gateway is unavailable") from exc
        if completion.metadata != self._metadata:
            raise ModelProviderResponseError("model gateway metadata does not match client profile")
        return completion


def create_model_gateway_app(
    *,
    providers: Mapping[str, ModelProvider],
    service_authorizer: ServiceAuthorizer,
) -> Any:
    """Create the private model service with an explicit service-auth seam."""

    if not providers or any(
        not isinstance(provider, ModelProvider) for provider in providers.values()
    ):
        raise TypeError("model gateway requires provider-neutral installed providers")
    if not callable(service_authorizer):
        raise TypeError("model gateway service authorizer is required")

    from fastapi import FastAPI

    application = FastAPI(
        title="RECLAIM Model Gateway",
        version=MODEL_GATEWAY_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    router = APIRouter()

    @router.post("/v1/model/complete", response_model=ModelGatewayResponse)
    def complete(
        body: ModelGatewayRequest,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> ModelGatewayResponse:
        _authorize(authorization, service_authorizer)
        provider = providers.get(body.profile)
        if provider is None:
            raise HTTPException(status_code=403, detail="model profile is not authorized")
        try:
            completion = provider.complete(
                body.request,
                tool_results=tuple(result.to_domain() for result in body.tool_results),
            )
        except ModelProviderUnavailable as exc:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(status_code=503, detail="model provider is unavailable") from exc
        except ModelProviderError as exc:
            raise HTTPException(status_code=422, detail="model response was rejected") from exc
        return ModelGatewayResponse.from_completion(completion)

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


__all__ = [
    "MODEL_GATEWAY_VERSION",
    "ModelGatewayClient",
    "ModelGatewayRequest",
    "ModelGatewayResponse",
    "ToolResultEnvelope",
    "create_model_gateway_app",
]
