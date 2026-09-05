"""Private, help-only model gateway runtime."""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable, Mapping
from typing import Any

from agent.providers import ModelProviderError, ModelProviderUnavailable
from fastapi import FastAPI, Header, HTTPException, status
from packages.contracts.help_chat import HelpGatewayRequest, HelpGatewayResponse

from .help_provider import build_help_provider

ServiceProvider = Callable[[HelpGatewayRequest], HelpGatewayResponse]
SERVICE_TOKEN_ENV = "RECLAIM_HELP_GATEWAY_TOKEN"


def create_model_gateway_app(
    *,
    help_provider: ServiceProvider | None = None,
    service_token: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    """Create the private runtime with exactly one authenticated operation."""

    env = dict(os.environ if environ is None else environ)
    provider = build_help_provider(env) if help_provider is None else help_provider
    handler = provider if callable(provider) else getattr(provider, "complete", None)
    if not callable(handler):
        raise TypeError("help model provider must be callable")
    configured_token = service_token or env.get(SERVICE_TOKEN_ENV, "").strip()
    if not configured_token:
        raise ValueError(f"{SERVICE_TOKEN_ENV} is required")

    application = FastAPI(
        title="RECLAIM Private Help Model Gateway",
        version="help-model-gateway-v1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.post("/v1/help/complete", response_model=HelpGatewayResponse)
    def complete_help(
        body: HelpGatewayRequest,
        authorization: str | None = Header(default=None),
    ) -> HelpGatewayResponse:
        _authorize(authorization, configured_token)
        try:
            result = handler(body)
            return (
                result
                if isinstance(result, HelpGatewayResponse)
                else HelpGatewayResponse.model_validate(result)
            )
        except ModelProviderUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="help model provider is unavailable",
            ) from exc
        except (ModelProviderError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="help model response was rejected",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="help model provider is unavailable",
            ) from exc

    return application


def build_app_from_environment(
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    return create_model_gateway_app(environ=environ)


def _authorize(authorization: str | None, expected_token: str) -> None:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service authentication is required",
        )
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service authentication is required",
        )
    if not hmac.compare_digest(token.strip(), expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="service is not authorized",
        )


def main() -> int:
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(build_app_from_environment(), host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())


__all__ = ["SERVICE_TOKEN_ENV", "build_app_from_environment", "create_model_gateway_app", "main"]
