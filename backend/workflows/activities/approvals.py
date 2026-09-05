"""Small Temporal activity adapters for approval lifecycle commands.

Activities delegate to the approval service.  They never invoke an action;
Temporal owns retry/orchestration while PostgreSQL-backed service wiring owns
the approval record.
"""

from __future__ import annotations

from typing import Any

from approvals.service import ApprovalService


def request_approval(service: ApprovalService, **kwargs: Any) -> Any:
    return service.request_approval(**kwargs)


def approve_approval(service: ApprovalService, request: Any, **kwargs: Any) -> Any:
    return service.approve(request, **kwargs)


def reject_approval(service: ApprovalService, request: Any, **kwargs: Any) -> Any:
    return service.reject(request, **kwargs)


def expire_approval(service: ApprovalService, approval_id: str, **kwargs: Any) -> Any:
    return service.expire(approval_id, **kwargs)


def revoke_approval(service: ApprovalService, approval_id: str, **kwargs: Any) -> Any:
    return service.revoke(approval_id, **kwargs)


def authorize_approval(service: ApprovalService, **kwargs: Any) -> Any:
    return service.authorize_action(**kwargs)


def reevaluate_stale_policy(service: ApprovalService, **kwargs: Any) -> Any:
    return service.re_evaluate_stale_policy(**kwargs)


__all__ = [
    "approve_approval",
    "authorize_approval",
    "expire_approval",
    "reject_approval",
    "reevaluate_stale_policy",
    "request_approval",
    "revoke_approval",
]
