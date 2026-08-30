"""Shared live and simulator evidence connector runtime boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.auth.oidc import TenantAuthorizationContext, TenantAuthorizationError
from packages.contracts.connectors import (
    ConnectorFailureState,
    ConnectorManifest,
    ConnectorMode,
    EvidenceRequest,
    EvidenceResponse,
)

from .allowlist import validate_evidence_manifest, validate_evidence_request


class EvidenceConnectorError(RuntimeError):
    """A connector failure that must remain visible to orchestration."""

    def __init__(self, message: str, *, failure_state: ConnectorFailureState) -> None:
        super().__init__(message)
        self.failure_state = failure_state


class EvidencePayloadLimitError(EvidenceConnectorError):
    """Raised before an oversized connector response can reach storage."""


@dataclass(frozen=True, slots=True)
class EvidenceReadResult:
    """A contract response plus the immutable bytes obtained from the connector."""

    response: EvidenceResponse
    raw_payload: bytes
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.raw_payload, bytes):
            raise TypeError("raw evidence payload must be bytes")
        object.__setattr__(self, "provenance", dict(self.provenance))


@runtime_checkable
class EvidenceConnector(Protocol):
    """The common interface implemented by live and deterministic connectors."""

    @property
    def manifest(self) -> ConnectorManifest: ...

    def read(
        self,
        request: EvidenceRequest,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> EvidenceReadResult: ...


Reader = Callable[
    [EvidenceRequest], EvidenceReadResult | EvidenceResponse | tuple[EvidenceResponse, bytes]
]


class ReadOnlyEvidenceAdapter:
    """Adapter shell with tenant and allowlist checks before an injected read transport.

    The adapter does not construct URLs, probe credentials, or expose mutation
    methods.  A live transport is injected by the approved connector integration;
    a simulator supplies the same result type from deterministic fixtures.
    """

    def __init__(self, manifest: ConnectorManifest, *, reader: Reader) -> None:
        self._manifest = validate_evidence_manifest(manifest)
        self._reader = reader

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def read(
        self,
        request: EvidenceRequest,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> EvidenceReadResult:
        self._authorize(request, authorization_context)
        try:
            result = self._reader(request)
        except EvidenceConnectorError:
            raise
        except TimeoutError as exc:
            raise EvidenceConnectorError(
                "evidence connector timed out", failure_state=ConnectorFailureState.TIMEOUT
            ) from exc
        except Exception as exc:
            raise EvidenceConnectorError(
                "evidence connector is unavailable", failure_state=ConnectorFailureState.UNAVAILABLE
            ) from exc
        return self._coerce_result(request, result)

    collect = read

    def _authorize(
        self,
        request: EvidenceRequest,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        if not isinstance(authorization_context, TenantAuthorizationContext):
            raise TenantAuthorizationError("authenticated tenant authorization is required")
        if authorization_context.tenant_id != self._manifest.tenant_id:
            raise TenantAuthorizationError("connector authorization is not tenant-bound")
        if request.tenant_id != authorization_context.tenant_id:
            raise TenantAuthorizationError("evidence request tenant does not match authorization")
        validate_evidence_request(self._manifest, request)

    def _coerce_result(
        self,
        request: EvidenceRequest,
        result: EvidenceReadResult | EvidenceResponse | tuple[EvidenceResponse, bytes],
    ) -> EvidenceReadResult:
        if isinstance(result, EvidenceReadResult):
            read_result = result
        elif isinstance(result, EvidenceResponse):
            raw_payload = json.dumps(
                result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            read_result = EvidenceReadResult(result, raw_payload)
        elif isinstance(result, tuple) and len(result) == 2:
            response, raw_payload = result
            if not isinstance(response, EvidenceResponse) or not isinstance(raw_payload, bytes):
                raise EvidenceConnectorError(
                    "connector returned an invalid evidence response",
                    failure_state=ConnectorFailureState.INVALID,
                )
            read_result = EvidenceReadResult(response, raw_payload)
        else:
            raise EvidenceConnectorError(
                "connector returned an invalid evidence response",
                failure_state=ConnectorFailureState.INVALID,
            )

        if len(read_result.raw_payload) > self._manifest.limits.max_payload_bytes:
            raise EvidencePayloadLimitError(
                "connector response exceeds declared payload limit",
                failure_state=ConnectorFailureState.INVALID,
            )

        response = read_result.response
        if (
            response.tenant_id != request.tenant_id
            or response.case_id != request.case_id
            or response.connector_id != request.connector_id
            or response.resource_type != request.resource_type
            or response.correlation_id != request.correlation_id
        ):
            raise EvidenceConnectorError(
                "connector response identity does not match request",
                failure_state=ConnectorFailureState.INVALID,
            )
        return read_result


class LiveEvidenceConnector(ReadOnlyEvidenceAdapter):
    """A live-mode adapter; all network behavior stays in its injected transport."""

    def __init__(self, manifest: ConnectorManifest, *, reader: Reader) -> None:
        if manifest.mode is not ConnectorMode.LIVE:
            raise ValueError("live evidence connector requires a live manifest")
        super().__init__(manifest, reader=reader)
