"""Immutable, checksummed policy versions.

Policy definitions are values, not mutable runtime configuration.  A draft may
be published by the policy-owner boundary, but a published value can only be
replaced by a new version.  The database repository supplies the durable
authority; these types make the same invariant true before a database call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext

POLICY_SCHEMA_VERSION = "1.0.0"


class PolicyVersionError(ValueError):
    """Raised when a policy cannot be safely used or published."""


class PolicyScope(StrEnum):
    TENANT = "tenant"
    GLOBAL = "global"


class PolicyPublicationStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REVOKED = "revoked"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyVersionError(f"{name} is required")
    return value.strip()


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PolicyVersionError(f"{name} must include an explicit timezone")
    return value.astimezone(UTC)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return _utc(value, "timestamp").isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    """A validated policy value whose meaning is fixed by its checksum."""

    policy_version_id: str
    tenant_id: str | None
    scope_type: PolicyScope | str
    thresholds: Mapping[str, Any]
    action_allowlist: frozenset[str]
    approval_rules: Mapping[str, Any]
    effective_from: datetime
    effective_to: datetime | None
    author: str
    publication_status: PolicyPublicationStatus | str
    immutable_checksum: str
    schema_version: str = POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        policy_id = _required_text(self.policy_version_id, "policy_version_id")
        author = _required_text(self.author, "policy author")
        checksum = _required_text(self.immutable_checksum, "policy checksum").lower()
        try:
            scope = PolicyScope(self.scope_type)
            status = PolicyPublicationStatus(self.publication_status)
        except ValueError as exc:
            raise PolicyVersionError("policy scope or publication status is invalid") from exc
        if not isinstance(self.schema_version, str) or self.schema_version != POLICY_SCHEMA_VERSION:
            raise PolicyVersionError("unsupported policy schema version")
        tenant_id = None if self.tenant_id is None else _required_text(self.tenant_id, "tenant_id")
        if scope is PolicyScope.GLOBAL and tenant_id is not None:
            raise PolicyVersionError("global policy versions cannot carry a tenant")
        if scope is PolicyScope.TENANT and tenant_id is None:
            raise PolicyVersionError("tenant policy versions require a tenant")
        effective_from = _utc(self.effective_from, "effective_from")
        effective_to = (
            None if self.effective_to is None else _utc(self.effective_to, "effective_to")
        )
        if effective_to is not None and effective_to <= effective_from:
            raise PolicyVersionError("effective_to must be after effective_from")
        if not isinstance(self.thresholds, Mapping) or not isinstance(self.approval_rules, Mapping):
            raise PolicyVersionError("policy thresholds and approval rules must be objects")
        if not isinstance(self.action_allowlist, (set, frozenset, tuple, list)):
            raise PolicyVersionError("policy action allowlist must be a collection")
        actions = frozenset(
            _required_text(value, "policy action") for value in self.action_allowlist
        )
        if len(actions) != len(self.action_allowlist):
            raise PolicyVersionError("policy action allowlist must be unique")
        if len(checksum) != 64 or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            raise PolicyVersionError("policy checksum must be a lowercase SHA-256 digest")
        object.__setattr__(self, "policy_version_id", policy_id)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "scope_type", scope)
        object.__setattr__(self, "publication_status", status)
        object.__setattr__(self, "thresholds", _freeze(self.thresholds))
        object.__setattr__(self, "approval_rules", _freeze(self.approval_rules))
        object.__setattr__(self, "action_allowlist", actions)
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_to", effective_to)
        object.__setattr__(self, "author", author)
        object.__setattr__(self, "immutable_checksum", checksum)

    def payload(self) -> dict[str, Any]:
        """Return the policy content used for provenance and checksum calculation."""

        return {
            "schema_version": self.schema_version,
            "policy_version_id": self.policy_version_id,
            "tenant_id": self.tenant_id,
            "scope_type": self.scope_type.value,
            "thresholds": _json_value(self.thresholds),
            "action_allowlist": sorted(self.action_allowlist),
            "approval_rules": _json_value(self.approval_rules),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "author": self.author,
            "publication_status": self.publication_status.value,
        }

    def is_effective(self, at: datetime) -> bool:
        moment = _utc(at, "evaluation time")
        return (
            self.publication_status is PolicyPublicationStatus.PUBLISHED
            and self.effective_from <= moment
            and (self.effective_to is None or moment < self.effective_to)
        )

    @property
    def checksum(self) -> str:
        """Short alias used by audit and connector adapters."""

        return self.immutable_checksum

    @property
    def is_published(self) -> bool:
        return self.publication_status is PolicyPublicationStatus.PUBLISHED

    def with_publication_status(self, status: PolicyPublicationStatus | str) -> PolicyVersion:
        """Create a same-content value with a lifecycle status transition."""

        return build_policy_version(
            policy_version_id=self.policy_version_id,
            tenant_id=self.tenant_id,
            scope_type=self.scope_type,
            thresholds=self.thresholds,
            action_allowlist=self.action_allowlist,
            approval_rules=self.approval_rules,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            author=self.author,
            publication_status=status,
        )


def checksum_for_policy(policy: PolicyVersion | Mapping[str, Any]) -> str:
    """Compute the stable SHA-256 identity of a policy's complete meaning."""

    if isinstance(policy, PolicyVersion):
        payload = policy.payload()
        # Draft -> published is a lifecycle transition, not a change in the
        # policy meaning.  Keeping status out of the digest preserves the
        # stable identity/checksum of the published version.
        payload.pop("publication_status", None)
    elif isinstance(policy, Mapping):
        payload = dict(policy)
        payload.pop("immutable_checksum", None)
        payload.pop("publication_status", None)
        payload = _json_value(payload)
    else:
        raise PolicyVersionError("policy checksum input must be a policy or object")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_policy_checksum(policy: PolicyVersion | Mapping[str, Any]) -> None:
    if not isinstance(policy, PolicyVersion):
        raise PolicyVersionError("only a validated PolicyVersion can be evaluated")
    if checksum_for_policy(policy) != policy.immutable_checksum:
        raise PolicyVersionError("policy checksum is invalid")


def build_policy_version(
    *,
    policy_version_id: str,
    tenant_id: str | None,
    scope_type: PolicyScope | str = PolicyScope.TENANT,
    thresholds: Mapping[str, Any],
    action_allowlist: list[str] | tuple[str, ...] | frozenset[str],
    approval_rules: Mapping[str, Any],
    effective_from: datetime,
    effective_to: datetime | None,
    author: str,
    publication_status: PolicyPublicationStatus | str = PolicyPublicationStatus.DRAFT,
) -> PolicyVersion:
    if isinstance(action_allowlist, Mapping):
        raise PolicyVersionError("policy action allowlist must be a sequence of action names")
    candidate = PolicyVersion(
        policy_version_id=policy_version_id,
        tenant_id=tenant_id,
        scope_type=scope_type,
        thresholds=thresholds,
        action_allowlist=frozenset(action_allowlist),
        approval_rules=approval_rules,
        effective_from=effective_from,
        effective_to=effective_to,
        author=author,
        publication_status=publication_status,
        immutable_checksum="0" * 64,
    )
    candidate_values = {
        "policy_version_id": candidate.policy_version_id,
        "tenant_id": candidate.tenant_id,
        "scope_type": candidate.scope_type,
        "thresholds": candidate.thresholds,
        "action_allowlist": candidate.action_allowlist,
        "approval_rules": candidate.approval_rules,
        "effective_from": candidate.effective_from,
        "effective_to": candidate.effective_to,
        "author": candidate.author,
        "publication_status": candidate.publication_status,
        "schema_version": candidate.schema_version,
        "immutable_checksum": checksum_for_policy(candidate),
    }
    return PolicyVersion(**candidate_values)


def publish_policy_version(
    policy: PolicyVersion,
    *,
    authorization_context: TenantAuthorizationContext | None = None,
    actor: str | None = None,
    actor_role: str | None = None,
) -> PolicyVersion:
    """Publish a draft only through an authenticated policy-owner identity."""

    verify_policy_checksum(policy)
    if policy.publication_status is not PolicyPublicationStatus.DRAFT:
        raise PolicyVersionError("only a draft policy may be published")
    subject = actor
    if authorization_context is not None:
        if (
            policy.scope_type is PolicyScope.TENANT
            and authorization_context.tenant_id != policy.tenant_id
        ):
            raise PolicyVersionError("policy publication crosses tenant scope")
        if authorization_context.identity_type is not IdentityType.USER:
            raise PolicyVersionError("service and model identities cannot publish policy")
        try:
            authorization_context.require_role(RequiredRole.POLICY_OWNER)
        except PermissionError as exc:
            raise PolicyVersionError("policy-owner role is required to publish policy") from exc
        subject = authorization_context.subject
    elif actor_role != RequiredRole.POLICY_OWNER.value:
        raise PolicyVersionError("authenticated policy-owner authority is required")
    if not subject or not subject.strip():
        raise PolicyVersionError("policy publication actor is required")
    return policy.with_publication_status(PolicyPublicationStatus.PUBLISHED)


__all__ = [
    "POLICY_SCHEMA_VERSION",
    "PolicyPublicationStatus",
    "PolicyScope",
    "PolicyVersion",
    "PolicyVersionError",
    "build_policy_version",
    "checksum_for_policy",
    "publish_policy_version",
    "verify_policy_checksum",
]
