"""Versioned policy change control with optimistic concurrency."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime

from app.auth.oidc import TenantAuthorizationContext

from .tenant_configuration import (
    PolicyConfigurationValidation,
    validate_tenant_policy_configuration,
)
from .versions import PolicyVersion, PolicyVersionError, publish_policy_version


@dataclass(frozen=True, slots=True)
class PolicyChange:
    change_id: str
    tenant_id: str
    base_policy_version_id: str | None
    proposed_policy_version: PolicyVersion
    requested_by: str
    requested_at: datetime
    status: str = "pending"

    def __post_init__(self) -> None:
        if (
            not self.change_id.strip()
            or not self.tenant_id.strip()
            or not self.requested_by.strip()
        ):
            raise ValueError("policy change identity is required")
        if self.proposed_policy_version.tenant_id != self.tenant_id:
            raise ValueError("policy change crosses tenant scope")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("policy change timestamp requires timezone")


@dataclass(frozen=True, slots=True)
class PolicyChangeResult:
    accepted: bool
    change_id: str
    policy_version: PolicyVersion | None
    audit_reference: str
    reason: str


class PolicyChangeController:
    """Coordinate bounded validation and policy-owner publication."""

    def __init__(self) -> None:
        self._changes: dict[tuple[str, str], PolicyChange] = {}

    def validate(
        self,
        *,
        tenant_id: str,
        change: str,
        thresholds: object,
        actor_role: str | None = None,
        action_allowlist: tuple[str, ...] = (),
        authorization_context: TenantAuthorizationContext | None = None,
    ) -> PolicyConfigurationValidation:
        return validate_tenant_policy_configuration(
            tenant_id=tenant_id,
            change=change,
            thresholds=thresholds,
            actor_role=actor_role,
            action_allowlist=action_allowlist,
            authorization_context=authorization_context,
        )

    def submit(
        self, change: PolicyChange, *, expected_base_version_id: str | None = None
    ) -> PolicyChange:
        if expected_base_version_id != change.base_policy_version_id:
            raise PolicyVersionError("policy change has a stale base version")
        key = (change.tenant_id, change.change_id)
        if key in self._changes and self._changes[key] != change:
            raise PolicyVersionError("policy change identity is already used")
        self._changes[key] = change
        return change

    def get(self, *, tenant_id: str, change_id: str) -> PolicyChange | None:
        return self._changes.get((tenant_id, change_id))

    def publish(
        self,
        change: PolicyChange,
        *,
        authorization_context: TenantAuthorizationContext | None = None,
        actor_role: str | None = None,
        expected_change_status: str = "pending",
    ) -> PolicyChangeResult:
        current = self._changes.get((change.tenant_id, change.change_id))
        if current != change or change.status != expected_change_status:
            return self._rejected(change, "policy change is stale or was not submitted")
        try:
            published = publish_policy_version(
                change.proposed_policy_version,
                authorization_context=authorization_context,
                actor=change.requested_by if authorization_context is None else None,
                actor_role=actor_role,
            )
        except PolicyVersionError as exc:
            return self._rejected(change, str(exc))
        self._changes[(change.tenant_id, change.change_id)] = replace(change, status="published")
        return PolicyChangeResult(True, change.change_id, published, _audit_id(change), "published")

    @staticmethod
    def _rejected(change: PolicyChange, reason: str) -> PolicyChangeResult:
        return PolicyChangeResult(False, change.change_id, None, _audit_id(change), reason)


def _audit_id(change: PolicyChange) -> str:
    return (
        "policy-change:"
        + hashlib.sha256(
            f"{change.tenant_id}:{change.change_id}:{change.proposed_policy_version.immutable_checksum}".encode()
        ).hexdigest()
    )


__all__ = ["PolicyChange", "PolicyChangeController", "PolicyChangeResult"]
