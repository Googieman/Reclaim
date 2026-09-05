"""Canonical action identity and durable execution idempotency.

The proposal occurrence (analysis/proposal IDs and the supplied idempotency key)
is provenance.  The gateway accepts only the canonical identity produced by the
deterministic proposal validator as its action idempotency identity.  This module
contains the small in-memory seam used by deterministic tests and the protocol
used by the PostgreSQL repository; production wiring must use PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol

from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest
from packages.contracts.analysis_policy import TypedActionProposal

ACTION_IDEMPOTENCY_VERSION = "action-idempotency-v1.0.0"


class ActionIdempotencyError(ValueError):
    """Raised when an action identity is missing, forged, or reused inconsistently."""


class ExecutionStore(Protocol):
    def begin(self, **kwargs: Any) -> tuple[ActionExecutionRecord, bool]: ...

    def get_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> ActionExecutionRecord | None: ...

    def update(self, record: ActionExecutionRecord, **changes: Any) -> ActionExecutionRecord: ...


@dataclass(frozen=True, slots=True)
class ActionExecutionRecord:
    """A durable action lifecycle snapshot.

    ``attempt_count`` is the count of provider requests, not the count of local
    duplicate commands.  A duplicate command returns this same record and does
    not increment the count or invoke the provider again.
    """

    tenant_id: str
    case_id: str
    proposal_id: str
    canonical_action_id: str
    execution_id: str
    connector_id: str
    resource_type: str
    target_resource: str
    idempotency_key: str
    provider_idempotency_key: str
    request_checksum: str
    policy_decision_id: str
    approval_id: str | None
    status: ActionExecutionState
    attempt_count: int = 0
    remote_reference: str | None = None
    result_reference: str | None = None
    reconciliation_state: str = "not_required"
    last_remote_result: str | None = None
    last_reconciled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "case_id",
            "proposal_id",
            "canonical_action_id",
            "execution_id",
            "connector_id",
            "resource_type",
            "target_resource",
            "idempotency_key",
            "provider_idempotency_key",
            "request_checksum",
            "policy_decision_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ActionIdempotencyError(f"{name} is required")
        if isinstance(self.attempt_count, bool) or self.attempt_count < 0:
            raise ActionIdempotencyError("attempt_count must be a non-negative integer")
        if self.status is ActionExecutionState.UNKNOWN and self.reconciliation_state not in {
            "required",
            "in_progress",
            "unresolved",
        }:
            raise ActionIdempotencyError("unknown execution must require reconciliation")
        for timestamp in (self.created_at, self.updated_at, self.last_reconciled_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ActionIdempotencyError("execution timestamps must be timezone-aware")


def derive_action_idempotency_key(
    proposal: TypedActionProposal | Mapping[str, Any],
    *,
    connector_id: str,
    authoritative_resource: object | Mapping[str, Any],
) -> str:
    """Derive the canonical semantic identity used by the Action Gateway.

    This intentionally mirrors the already-approved T075 identity inputs and
    excludes analysis/proposal IDs, caller/model keys, rationale, evidence order,
    provider/model metadata, timestamps, and cost metadata.
    """

    values = (
        proposal.model_dump(mode="json")
        if isinstance(proposal, TypedActionProposal)
        else dict(proposal)
        if isinstance(proposal, Mapping)
        else None
    )
    if values is None:
        raise TypeError("proposal must be a TypedActionProposal or mapping")
    resource = _values(authoritative_resource)
    required = {
        "tenant_id": resource.get("tenant_id"),
        "case_id": resource.get("case_id"),
        "target_resource_id": resource.get("resource_id", resource.get("id")),
        "resource_type": resource.get("resource_type"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in required.values()):
        raise ActionIdempotencyError("authoritative resource identity is incomplete")
    if resource.get("connector_id") != connector_id:
        raise ActionIdempotencyError("authoritative resource connector does not match action")
    action_type = values.get("action_type")
    action_value = getattr(action_type, "value", action_type)
    if not isinstance(action_value, str) or not action_value.strip():
        raise ActionIdempotencyError("action type is required for canonical identity")
    payload = {
        "identity_version": "action-identity-v1.0.0",
        "schema_version": values.get("schema_version", "1.0.0"),
        "tenant_id": required["tenant_id"],
        "case_id": required["case_id"],
        "action_type": action_value,
        "connector_id": connector_id,
        "target_resource_id": required["target_resource_id"],
        "resource_type": required["resource_type"],
        "parameters": values.get("parameters", {}),
        "requested_amount_minor": values.get("requested_amount_minor"),
        "currency": values.get("currency"),
    }
    return _sha256(payload)


def require_matching_canonical_identity(
    request: ActionGatewayRequest,
    *,
    canonical_action_id: str,
) -> str:
    """Reject a request whose gateway key is not the authoritative identity."""

    if not isinstance(request, ActionGatewayRequest):
        raise TypeError("request must be an ActionGatewayRequest")
    if not isinstance(canonical_action_id, str) or not canonical_action_id.strip():
        raise ActionIdempotencyError("canonical action identity is required")
    if request.idempotency_key != canonical_action_id:
        raise ActionIdempotencyError(
            "supplied gateway idempotency key does not match canonical action identity"
        )
    return canonical_action_id


def execution_id_for(*, tenant_id: str, canonical_action_id: str) -> str:
    """Return a stable lifecycle identity for one tenant/canonical action pair."""

    return "execution:" + _sha256(
        {
            "version": ACTION_IDEMPOTENCY_VERSION,
            "tenant_id": tenant_id,
            "canonical_action_id": canonical_action_id,
        }
    )


def provider_idempotency_key_for(canonical_action_id: str) -> str:
    """Return a provider-facing token distinct from the canonical action key."""

    return (
        "provider:"
        + hashlib.sha256(f"{ACTION_IDEMPOTENCY_VERSION}:{canonical_action_id}".encode()).hexdigest()
    )


class InMemoryActionExecutionStore:
    """Atomic deterministic test seam; not a production business store."""

    def __init__(self) -> None:
        self._records: MutableMapping[tuple[str, str], ActionExecutionRecord] = {}
        self._lock = RLock()

    def begin(
        self,
        *,
        request: ActionGatewayRequest,
        canonical_action_id: str | None = None,
        resource_type: str,
        provider_idempotency_key: str | None = None,
        execution_id: str | None = None,
        policy_decision_id: str,
        approval_id: str | None = None,
    ) -> tuple[ActionExecutionRecord, bool]:
        canonical = require_matching_canonical_identity(
            request, canonical_action_id=canonical_action_id or request.idempotency_key
        )
        now = datetime.now(UTC)
        candidate = ActionExecutionRecord(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            canonical_action_id=canonical,
            execution_id=execution_id
            or execution_id_for(tenant_id=request.tenant_id, canonical_action_id=canonical),
            connector_id=request.connector_id,
            resource_type=resource_type,
            target_resource=request.target_resource,
            idempotency_key=request.idempotency_key,
            provider_idempotency_key=provider_idempotency_key
            or provider_idempotency_key_for(canonical),
            request_checksum=request.request_checksum,
            policy_decision_id=policy_decision_id,
            approval_id=approval_id,
            status=ActionExecutionState.RECEIVED,
            created_at=now,
            updated_at=now,
            correlation_id=request.correlation_id,
        )
        key = (candidate.tenant_id, candidate.canonical_action_id)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                _assert_same_semantic_request(existing, candidate)
                return existing, False
            self._records[key] = candidate
            return candidate, True

    def get_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> ActionExecutionRecord | None:
        with self._lock:
            return next(
                (
                    record
                    for (record_tenant, _), record in self._records.items()
                    if record_tenant == tenant_id and record.idempotency_key == idempotency_key
                ),
                None,
            )

    def get(self, *, tenant_id: str, canonical_action_id: str) -> ActionExecutionRecord | None:
        with self._lock:
            return self._records.get((tenant_id, canonical_action_id))

    def update(self, record: ActionExecutionRecord, **changes: Any) -> ActionExecutionRecord:
        updated = replace(record, **changes, updated_at=datetime.now(UTC))
        with self._lock:
            current = self._records.get((record.tenant_id, record.canonical_action_id))
            if current != record:
                raise ActionIdempotencyError("execution update lost an authoritative race")
            self._records[(record.tenant_id, record.canonical_action_id)] = updated
        return updated


def _assert_same_semantic_request(
    existing: ActionExecutionRecord, candidate: ActionExecutionRecord
) -> None:
    fields = (
        "tenant_id",
        "case_id",
        "canonical_action_id",
        "connector_id",
        "resource_type",
        "target_resource",
        "idempotency_key",
        "request_checksum",
        "policy_decision_id",
        "approval_id",
    )
    if any(getattr(existing, field) != getattr(candidate, field) for field in fields):
        raise ActionIdempotencyError("canonical action identity conflicts with existing execution")


def _values(value: object | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


stable_action_idempotency_key = derive_action_idempotency_key
canonical_action_idempotency_key = derive_action_idempotency_key


__all__ = [
    "ACTION_IDEMPOTENCY_VERSION",
    "ActionExecutionRecord",
    "ActionIdempotencyError",
    "ExecutionStore",
    "InMemoryActionExecutionStore",
    "canonical_action_idempotency_key",
    "derive_action_idempotency_key",
    "execution_id_for",
    "provider_idempotency_key_for",
    "require_matching_canonical_identity",
    "stable_action_idempotency_key",
]
