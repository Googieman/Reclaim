"""Versioned manifests for the two defensive US3 simulator actions."""

from __future__ import annotations

from packages.contracts.connectors import (
    ConnectorFailureState,
    ConnectorLimits,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)

ACTION_CONTRACT_VERSION = "1.0.0"
ACTION_REQUEST_SCHEMA = "action.connector.request.v1"
ACTION_RESPONSE_SCHEMA = "action.connector.response.v1"


def build_session_action_manifest(
    tenant_id: str,
    *,
    mode: ConnectorMode | str = ConnectorMode.SIMULATOR,
) -> ConnectorManifest:
    return _manifest(
        tenant_id,
        connector_id="session-actions",
        resource="sessions",
        operation="revoke_suspicious_session",
        mode=mode,
        scope="sessions:revoke",
    )


def build_fulfillment_action_manifest(
    tenant_id: str,
    *,
    mode: ConnectorMode | str = ConnectorMode.SIMULATOR,
) -> ConnectorManifest:
    return _manifest(
        tenant_id,
        connector_id="fulfillment-actions",
        resource="fulfillment",
        operation="hold_fulfillment",
        mode=mode,
        scope="fulfillment:hold",
    )


def build_action_manifests(
    tenant_id: str,
    *,
    mode: ConnectorMode | str = ConnectorMode.SIMULATOR,
) -> dict[str, ConnectorManifest]:
    manifests = (
        build_session_action_manifest(tenant_id, mode=mode),
        build_fulfillment_action_manifest(tenant_id, mode=mode),
    )
    return {manifest.connector_id: manifest for manifest in manifests}


def _manifest(
    tenant_id: str,
    *,
    connector_id: str,
    resource: str,
    operation: str,
    mode: ConnectorMode | str,
    scope: str,
) -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id=tenant_id,
        correlation_id=f"manifest:{connector_id}:{tenant_id}",
        connector_id=connector_id,
        contract_version=ACTION_CONTRACT_VERSION,
        connector_type=ConnectorType.ACTION,
        mode=mode,
        resources=(resource,),
        operations=(operation,),
        auth_scope=(f"merchant:{tenant_id}:action:{scope}",),
        request_schema=ACTION_REQUEST_SCHEMA,
        response_schema=ACTION_RESPONSE_SCHEMA,
        limits=ConnectorLimits(timeout_seconds=30),
        timestamp_semantics="requested_at is an explicit UTC command timestamp",
        idempotency_behavior="connector receives the canonical gateway idempotency key",
        failure_states=tuple(ConnectorFailureState),
    )


__all__ = [
    "ACTION_CONTRACT_VERSION",
    "ACTION_REQUEST_SCHEMA",
    "ACTION_RESPONSE_SCHEMA",
    "build_action_manifests",
    "build_fulfillment_action_manifest",
    "build_session_action_manifest",
]
