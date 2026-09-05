"""Typed, bounded HTTP client for the private documentation-help gateway."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from packages.contracts.help_chat import HelpGatewayRequest, HelpGatewayResponse

DEFAULT_HELP_GATEWAY_TIMEOUT_SECONDS = 10.0
MAX_HELP_GATEWAY_TIMEOUT_SECONDS = 30.0
MAX_HELP_GATEWAY_RESPONSE_BYTES = 64 * 1024


class HelpGatewayUnavailable(RuntimeError):
    """Stable internal error for all unavailable gateway outcomes."""


class HttpHelpGateway:
    """Call the private help gateway without exposing transport controls."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = DEFAULT_HELP_GATEWAY_TIMEOUT_SECONDS,
        max_response_bytes: int = MAX_HELP_GATEWAY_RESPONSE_BYTES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _validate_base_url(base_url)
        if not isinstance(service_token, str) or not service_token.strip():
            raise ValueError("help gateway service token is required")
        if not 0 < timeout_seconds <= MAX_HELP_GATEWAY_TIMEOUT_SECONDS:
            raise ValueError("help gateway timeout is outside the allowed range")
        if not 1 <= max_response_bytes <= 1_048_576:
            raise ValueError("help gateway response limit is outside the allowed range")

        self._endpoint = base_url.rstrip("/") + "/v1/help/complete"
        self._service_token = service_token.strip()
        self._max_response_bytes = max_response_bytes
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def complete(self, request: HelpGatewayRequest) -> HelpGatewayResponse:
        if not isinstance(request, HelpGatewayRequest):
            raise HelpGatewayUnavailable("help gateway is unavailable")

        payload = request.model_dump(mode="json")
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                headers={"Authorization": f"Bearer {self._service_token}"},
                json=payload,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise HelpGatewayUnavailable("help gateway is unavailable")
                body = _read_bounded_body(response, self._max_response_bytes)
        except HelpGatewayUnavailable:
            raise
        except Exception:
            raise HelpGatewayUnavailable("help gateway is unavailable") from None

        try:
            decoded = json.loads(body)
            return HelpGatewayResponse.model_validate(decoded)
        except Exception:
            raise HelpGatewayUnavailable("help gateway is unavailable") from None

    __call__ = complete


def _read_bounded_body(response: httpx.Response, max_response_bytes: int) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_response_bytes:
                raise HelpGatewayUnavailable("help gateway is unavailable")
        except ValueError:
            pass

    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > max_response_bytes:
            raise HelpGatewayUnavailable("help gateway is unavailable")
    return bytes(body)


def _validate_base_url(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("help gateway endpoint must be an HTTP(S) URL")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("help gateway endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("help gateway endpoint cannot embed credentials or controls")


__all__ = [
    "DEFAULT_HELP_GATEWAY_TIMEOUT_SECONDS",
    "HelpGatewayUnavailable",
    "HttpHelpGateway",
    "MAX_HELP_GATEWAY_RESPONSE_BYTES",
    "MAX_HELP_GATEWAY_TIMEOUT_SECONDS",
]
