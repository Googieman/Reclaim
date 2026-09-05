"""Authenticated approval lifecycle and exact action authorization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext
from app.db.repositories.approvals import ApprovalRepository
from packages.contracts.analysis_policy import Approval, ApprovalStatus


class ApprovalError(ValueError):
    """Raised when an approval lifecycle operation fails closed."""


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tenant_id: str
    case_id: str
    proposal_id: str
    action_type: str
    target_resource: str
    proposer_id: str
    policy_version_id: str
    correlation_id: str
    requested_at: datetime
    request_id: str
    expected_version: int = 0

    @property
    def scope(self) -> str:
        return f"{self.action_type}:{self.target_resource}"


@dataclass(frozen=True, slots=True)
class ApprovalAuthorization:
    execution_authorized: bool
    reason: str
    approval: Approval | None = None

    @property
    def authorized(self) -> bool:
        return self.execution_authorized


class ApprovalStore(Protocol):
    def save(self, approval: Approval, *, expected_version: int | None = None) -> Any: ...

    def get(self, approval_id: str, *, tenant_id: str) -> Approval | None: ...

    def version_of(self, approval_id: str, *, tenant_id: str) -> int | None: ...


class InMemoryApprovalStore:
    """Deterministic test seam; production wiring must use PostgreSQL."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], Approval] = {}
        self._versions: dict[tuple[str, str], int] = {}

    def save(self, approval: Approval, *, expected_version: int | None = None) -> Approval:
        key = (approval.tenant_id, approval.approval_id)
        version = self._versions.get(key, 0)
        if expected_version is not None and expected_version != version:
            raise ApprovalError("approval version race or stale decision")
        self._records[key] = approval
        self._versions[key] = version + 1
        return approval

    def get(self, approval_id: str, *, tenant_id: str) -> Approval | None:
        return self._records.get((tenant_id, approval_id))

    def version_of(self, approval_id: str, *, tenant_id: str) -> int | None:
        return self._versions.get((tenant_id, approval_id))


class PostgresApprovalStore:
    """Adapt the tenant-scoped PostgreSQL repository to the service protocol."""

    def __init__(self, repository: ApprovalRepository) -> None:
        self.repository = repository

    def save(self, approval: Approval, *, expected_version: int | None = None) -> Approval:
        self.repository.assert_tenant(approval.tenant_id)
        current_row = self.repository.get(approval_id=approval.approval_id)
        if current_row is None:
            self.repository.create(
                approval_id=approval.approval_id,
                correlation_id=approval.correlation_id,
                case_id=approval.case_id,
                proposal_id=approval.proposal_id,
                approver_id=approval.approver_id,
                approver_role=approval.approver_role,
                proposer_id=approval.proposer_id,
                scope=approval.scope,
                policy_version_id=approval.policy_version_id,
                status=approval.status.value,
                approved_at=approval.approved_at,
                expires_at=approval.expires_at,
                separation_of_duties_evidence=approval.separation_of_duties_evidence,
            )
            return approval
        current = _approval_from_row(current_row)
        if not _same_approval_identity(current, approval):
            raise ApprovalError("approval identity conflicts with the authoritative record")
        version = self.version_of(approval.approval_id, tenant_id=approval.tenant_id)
        if version is None:
            raise ApprovalError("approval version is unavailable")
        self.repository.update_status(
            approval_id=approval.approval_id,
            status=approval.status.value,
            expected_version=version if expected_version is None else expected_version,
        )
        return approval

    def get(self, approval_id: str, *, tenant_id: str) -> Approval | None:
        self.repository.assert_tenant(tenant_id)
        row = self.repository.get(approval_id=approval_id)
        return None if row is None else _approval_from_row(row)

    def version_of(self, approval_id: str, *, tenant_id: str) -> int | None:
        self.repository.assert_tenant(tenant_id)
        row = self.repository.get(approval_id=approval_id)
        if row is None:
            return None
        return int(row[13])


class ApprovalService:
    """Manage approvals without ever invoking or submitting an action."""

    def __init__(
        self, *, store: ApprovalStore | None = None, default_expiry: timedelta = timedelta(hours=1)
    ) -> None:
        if default_expiry <= timedelta(0):
            raise ValueError("approval expiry must be positive")
        self.store = store or InMemoryApprovalStore()
        self.default_expiry = default_expiry
        self._requests: dict[tuple[str, str], ApprovalRequest] = {}

    def request_approval(
        self,
        *,
        tenant_id: str,
        case_id: str,
        proposal_id: str,
        action_type: str,
        target_resource: str,
        proposer_id: str,
        policy_version_id: str,
        correlation_id: str,
        requested_at: datetime,
        request_id: str | None = None,
        expected_version: int = 0,
    ) -> ApprovalRequest:
        requested_at = _utc(requested_at, "approval request time")
        values = (
            tenant_id,
            case_id,
            proposal_id,
            action_type,
            target_resource,
            proposer_id,
            policy_version_id,
            correlation_id,
        )
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ApprovalError("approval request binding is incomplete")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 0
        ):
            raise ApprovalError("approval request version is malformed")
        request = ApprovalRequest(
            tenant_id=tenant_id,
            case_id=case_id,
            proposal_id=proposal_id,
            action_type=action_type,
            target_resource=target_resource,
            proposer_id=proposer_id,
            policy_version_id=policy_version_id,
            correlation_id=correlation_id,
            requested_at=requested_at,
            request_id=request_id or f"approval-request-{uuid4().hex}",
            expected_version=expected_version,
        )
        request_key = (tenant_id, request.request_id)
        existing = self._requests.get(request_key)
        if existing is not None and existing != request:
            raise ApprovalError("approval request identity is already used")
        self._requests[request_key] = request
        return request

    create_request = request_approval

    def approve(
        self,
        request: ApprovalRequest | str,
        *,
        approver_context: TenantAuthorizationContext,
        approver_role: str = RequiredRole.APPROVER.value,
        approved_at: datetime | None = None,
        expires_at: datetime | None = None,
        expected_version: int | None = None,
        approval_id: str | None = None,
    ) -> Approval:
        bound_request = self._request(request, approver_context.tenant_id)
        _require_approver(approver_context, bound_request.tenant_id)
        when = _utc(approved_at or datetime.now(UTC), "approval time")
        expiry = _utc(expires_at or when + self.default_expiry, "approval expiry")
        if expiry <= when:
            raise ApprovalError("approval expiry must be after approval time")
        if approver_context.subject == bound_request.proposer_id:
            raise ApprovalError("approver and proposer must be distinct")
        if approver_role != RequiredRole.APPROVER.value:
            raise ApprovalError("approval role must be the authenticated approver role")
        approval = Approval(
            tenant_id=bound_request.tenant_id,
            correlation_id=bound_request.correlation_id,
            approval_id=approval_id or f"approval-{uuid4().hex}",
            case_id=bound_request.case_id,
            proposal_id=bound_request.proposal_id,
            approver_id=approver_context.subject,
            approver_role=approver_role,
            proposer_id=bound_request.proposer_id,
            scope=bound_request.scope,
            policy_version_id=bound_request.policy_version_id,
            status=ApprovalStatus.APPROVED,
            approved_at=when,
            expires_at=expiry,
            separation_of_duties_evidence="distinct authenticated principals",
        )
        self.store.save(
            approval,
            expected_version=(
                bound_request.expected_version if expected_version is None else expected_version
            ),
        )
        return approval

    def reject(
        self,
        request: ApprovalRequest | str,
        *,
        approver_context: TenantAuthorizationContext,
        approved_at: datetime | None = None,
        expected_version: int | None = None,
        approval_id: str | None = None,
    ) -> Approval:
        bound_request = self._request(request, approver_context.tenant_id)
        _require_approver(approver_context, bound_request.tenant_id)
        when = _utc(approved_at or datetime.now(UTC), "approval decision time")
        approval = self._lifecycle_record(
            bound_request,
            approver_context=approver_context,
            status=ApprovalStatus.REJECTED,
            approved_at=when,
            approval_id=approval_id,
        )
        self.store.save(
            approval,
            expected_version=(
                bound_request.expected_version if expected_version is None else expected_version
            ),
        )
        return approval

    def expire(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        at: datetime | None = None,
        expected_version: int | None = None,
    ) -> Approval:
        current = self._stored(approval_id, tenant_id)
        when = _utc(at or datetime.now(UTC), "expiry time")
        if current is None:
            raise ApprovalError("approval is not present for this tenant")
        if current.status is not ApprovalStatus.APPROVED:
            raise ApprovalError("only an approved approval can expire")
        if current.expires_at is not None and current.expires_at > when:
            raise ApprovalError("approval has not reached its expiry time")
        expired = current.model_copy(update={"status": ApprovalStatus.EXPIRED})
        self.store.save(
            expired,
            expected_version=self._expected_version(approval_id, tenant_id, expected_version),
        )
        return expired

    def revoke(
        self, approval_id: str, *, tenant_id: str, expected_version: int | None = None
    ) -> Approval:
        current = self._stored(approval_id, tenant_id)
        if current is None:
            raise ApprovalError("approval is not present for this tenant")
        if current.status is not ApprovalStatus.APPROVED:
            raise ApprovalError("only an approved approval can be revoked")
        revoked = current.model_copy(update={"status": ApprovalStatus.REVOKED})
        self.store.save(
            revoked,
            expected_version=self._expected_version(approval_id, tenant_id, expected_version),
        )
        return revoked

    def authorize_action(
        self,
        *,
        proposal: object | Mapping[str, Any],
        approval: Approval | Mapping[str, Any] | None = None,
        approver_context: TenantAuthorizationContext | None = None,
        expected_policy_version_id: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalAuthorization:
        return authorize_action(
            proposal=proposal,
            approval=approval,
            approval_store=self.store,
            approver_context=approver_context,
            expected_policy_version_id=expected_policy_version_id,
            now=now,
        )

    def re_evaluate_stale_policy(
        self,
        *,
        proposal: object | Mapping[str, Any],
        approval: Approval | Mapping[str, Any] | None,
        current_policy_version_id: str,
        approver_context: TenantAuthorizationContext | None = None,
        now: datetime | None = None,
    ) -> ApprovalAuthorization:
        """Recheck approval authority against the policy currently in force.

        Policy evaluation itself remains the deterministic evaluator's job.  This
        method prevents an approval bound to an older policy version from being
        reused after that evaluation has selected a newer version.
        """

        return self.authorize_action(
            proposal=proposal,
            approval=approval,
            approver_context=approver_context,
            expected_policy_version_id=current_policy_version_id,
            now=now,
        )

    reevaluate_stale_policy = re_evaluate_stale_policy

    def _request(self, request: ApprovalRequest | str, tenant_id: str) -> ApprovalRequest:
        if isinstance(request, ApprovalRequest):
            bound = request
            stored = self._requests.get((tenant_id, request.request_id))
            if stored != request:
                raise ApprovalError("approval request is not the authoritative service record")
        else:
            bound = self._requests.get((tenant_id, request))
        if bound is None or bound.tenant_id != tenant_id:
            raise ApprovalError("approval request is not bound to the authenticated tenant")
        return bound

    def _stored(self, approval_id: str, tenant_id: str) -> Approval | None:
        return self.store.get(approval_id, tenant_id=tenant_id)

    def _expected_version(
        self, approval_id: str, tenant_id: str, expected_version: int | None
    ) -> int:
        if expected_version is not None:
            return expected_version
        version_of = getattr(self.store, "version_of", None)
        if not callable(version_of):
            raise ApprovalError("approval version is required for a lifecycle transition")
        current = version_of(approval_id, tenant_id=tenant_id)
        if current is None:
            raise ApprovalError("approval version is unavailable")
        return int(current)

    @staticmethod
    def _lifecycle_record(
        request: ApprovalRequest,
        *,
        approver_context: TenantAuthorizationContext,
        status: ApprovalStatus,
        approved_at: datetime,
        approval_id: str | None,
    ) -> Approval:
        if approver_context.subject == request.proposer_id:
            raise ApprovalError("approver and proposer must be distinct")
        return Approval(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            approval_id=approval_id or f"approval-{uuid4().hex}",
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            approver_id=approver_context.subject,
            approver_role=RequiredRole.APPROVER.value,
            proposer_id=request.proposer_id,
            scope=request.scope,
            policy_version_id=request.policy_version_id,
            status=status,
            approved_at=approved_at,
            expires_at=approved_at + timedelta(hours=1),
            separation_of_duties_evidence="distinct authenticated principals",
        )


def authorize_action(
    *,
    proposal: object | Mapping[str, Any],
    approval: Approval | Mapping[str, Any] | None,
    approval_store: ApprovalStore | None = None,
    approver_context: TenantAuthorizationContext | None = None,
    expected_policy_version_id: str | None = None,
    now: datetime | None = None,
) -> ApprovalAuthorization:
    """Prove exact approval authority for one proposal.

    A direct caller without an authoritative store is deliberately denied.  A
    payload-shaped mapping is untrusted input and is never treated as an
    approval record, which prevents forged IDs and model-authored approvals.
    """

    proposal_values = _values(proposal)
    if not isinstance(approval, Approval):
        return ApprovalAuthorization(False, "approval is not an authenticated contract record")
    if approval_store is None:
        return ApprovalAuthorization(False, "authoritative approval store is required")
    tenant = _text(proposal_values.get("tenant_id"))
    case_id = _text(proposal_values.get("case_id"))
    proposal_id = _text(proposal_values.get("proposal_id"))
    policy_version_id = (
        _text(proposal_values.get("policy_version_id")) or expected_policy_version_id
    )
    action = _text(proposal_values.get("action_type") or proposal_values.get("action"))
    target = _text(proposal_values.get("target_resource"))
    proposer = _text(proposal_values.get("proposer_id") or proposal_values.get("analysis_id"))
    if any(
        value is None
        for value in (tenant, case_id, proposal_id, policy_version_id, action, target, proposer)
    ):
        return ApprovalAuthorization(False, "proposal binding is incomplete")
    stored = approval_store.get(approval.approval_id, tenant_id=tenant)
    if stored is None or stored != approval:
        return ApprovalAuthorization(False, "approval is not the authoritative record")
    if (
        approval.tenant_id != tenant
        or approval.case_id != case_id
        or approval.proposal_id != proposal_id
    ):
        return ApprovalAuthorization(False, "approval does not match tenant, case, and proposal")
    if approval.policy_version_id != policy_version_id or (
        expected_policy_version_id is not None
        and approval.policy_version_id != expected_policy_version_id
    ):
        return ApprovalAuthorization(False, "approval does not match policy version")
    if approval.scope != f"{action}:{target}":
        return ApprovalAuthorization(False, "approval does not match the exact action scope")
    if approval.status is not ApprovalStatus.APPROVED:
        return ApprovalAuthorization(
            False, f"approval status {approval.status.value} cannot authorize action"
        )
    if approver_context is not None:
        try:
            _require_approver(approver_context, tenant)
        except ApprovalError as exc:
            return ApprovalAuthorization(False, str(exc))
        if approver_context.subject != approval.approver_id:
            return ApprovalAuthorization(
                False, "approval approver is not the authenticated approver"
            )
    moment = _utc(now or datetime.now(UTC), "authorization time")
    if approval.approved_at > moment:
        return ApprovalAuthorization(False, "approval is not effective yet")
    if approval.expires_at is not None and approval.expires_at <= moment:
        return ApprovalAuthorization(False, "approval has expired")
    if approval.approver_id == approval.proposer_id or approval.proposer_id != proposer:
        return ApprovalAuthorization(False, "approval violates proposer/approver separation")
    return ApprovalAuthorization(True, "exact approved action is authorized", approval)


def _require_approver(context: TenantAuthorizationContext, tenant_id: str) -> None:
    if context.tenant_id != tenant_id:
        raise ApprovalError("approver identity crosses tenant scope")
    if context.identity_type is not IdentityType.USER:
        raise ApprovalError("service and model identities cannot approve actions")
    try:
        context.require_role(RequiredRole.APPROVER)
    except PermissionError as exc:
        raise ApprovalError("approver role is required") from exc


def _values(value: object | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _same_approval_identity(left: Approval, right: Approval) -> bool:
    return left.model_copy(update={"status": right.status}) == right


def _approval_from_row(row: object) -> Approval:
    if isinstance(row, Mapping):
        values = dict(row)
        correlation_id = values.get("correlation_id")
        ordered = values
    else:
        ordered = {
            "tenant_id": row[0],
            "approval_id": row[1],
            "case_id": row[2],
            "proposal_id": row[3],
            "approver_id": row[4],
            "approver_role": row[5],
            "proposer_id": row[6],
            "scope": row[7],
            "policy_version_id": row[8],
            "status": row[9],
            "approved_at": row[10],
            "expires_at": row[11],
            "separation_of_duties_evidence": row[12],
            "correlation_id": row[15] if len(row) > 15 else None,
        }
        correlation_id = ordered["correlation_id"]
    return Approval(
        tenant_id=str(ordered["tenant_id"]),
        correlation_id=str(correlation_id or f"approval:{ordered['approval_id']}"),
        approval_id=str(ordered["approval_id"]),
        case_id=str(ordered["case_id"]),
        proposal_id=str(ordered["proposal_id"]),
        approver_id=str(ordered["approver_id"]),
        approver_role=str(ordered["approver_role"]),
        proposer_id=str(ordered["proposer_id"]),
        scope=str(ordered["scope"]),
        policy_version_id=str(ordered["policy_version_id"]),
        status=ApprovalStatus(str(ordered["status"])),
        approved_at=ordered["approved_at"],
        expires_at=ordered["expires_at"],
        separation_of_duties_evidence=str(ordered["separation_of_duties_evidence"]),
    )


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApprovalError(f"{name} must include an explicit timezone")
    return value.astimezone(UTC)


__all__ = [
    "ApprovalAuthorization",
    "ApprovalError",
    "ApprovalRequest",
    "ApprovalService",
    "InMemoryApprovalStore",
    "PostgresApprovalStore",
    "authorize_action",
]
