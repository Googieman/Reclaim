"""PostgreSQL repositories for immutable policies and historical decisions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext

from .base import RepositoryError, TenantScopedRepository


class PolicyVersionRepository(TenantScopedRepository):
    """Write policy drafts and publish them without changing published meaning."""

    def create(
        self,
        *,
        policy_version_id: str,
        scope_type: str,
        thresholds: Mapping[str, object],
        action_allowlist: Sequence[str],
        approval_rules: Mapping[str, object],
        effective_from: datetime,
        effective_to: datetime | None,
        author: str,
        publication_status: str,
        immutable_checksum: str,
    ) -> object:
        if scope_type not in {"tenant", "global"}:
            raise ValueError("policy scope_type must be tenant or global")
        if scope_type == "global":
            raise RepositoryError(
                "global policy versions are centrally managed outside tenant-scoped UoWs"
            )
        if not policy_version_id.strip() or not author.strip() or not immutable_checksum.strip():
            raise ValueError("policy version identity, author, and checksum are required")
        self._validate_status(publication_status)
        self._validate_tenant_scope(policy_version_id)
        row = self.fetch_one(
            """
            INSERT INTO public.policy_versions (
                policy_version_id, tenant_id, scope_type, thresholds, action_allowlist,
                approval_rules, effective_from, effective_to, author,
                publication_status, immutable_checksum
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING policy_version_id, tenant_id, scope_type, publication_status,
                      immutable_checksum
            """,
            (
                policy_version_id,
                self.tenant_context.tenant_id,
                scope_type,
                _json(thresholds),
                _json(list(action_allowlist)),
                _json(approval_rules),
                effective_from,
                effective_to,
                author,
                publication_status,
                immutable_checksum,
            ),
        )
        if row is None:
            raise RuntimeError("policy version insert returned no row")
        return row

    save = create

    def get(self, *, policy_version_id: str) -> object | None:
        if not policy_version_id.strip():
            raise ValueError("policy_version_id is required")
        return self.fetch_one(
            """
            SELECT policy_version_id, tenant_id, scope_type, thresholds,
                   action_allowlist, approval_rules, effective_from, effective_to,
                   author, publication_status, immutable_checksum
            FROM public.policy_versions
            WHERE policy_version_id = %s
              AND (tenant_id = %s OR tenant_id IS NULL)
            """,
            (policy_version_id, self.tenant_context.tenant_id),
        )

    find = get

    def publish(
        self,
        *,
        policy_version_id: str,
        actor: str,
        authorization_context: TenantAuthorizationContext | None = None,
        actor_role: str | None = None,
    ) -> object:
        """Activate a tenant draft; database trigger protects published rows."""

        if not actor.strip():
            raise RepositoryError("policy publication actor is required")
        if authorization_context is not None:
            if authorization_context.tenant_id != self.tenant_context.tenant_id:
                raise RepositoryError("policy publication crosses tenant scope")
            if authorization_context.identity_type is not IdentityType.USER:
                raise RepositoryError("service and model identities cannot publish policy")
            try:
                authorization_context.require_role(RequiredRole.POLICY_OWNER)
            except PermissionError as exc:
                raise RepositoryError("policy-owner role is required to publish policy") from exc
        elif actor_role != RequiredRole.POLICY_OWNER.value:
            raise RepositoryError("authenticated policy-owner authority is required")
        row = self.fetch_one(
            """
            UPDATE public.policy_versions
            SET publication_status = 'published'
            WHERE policy_version_id = %s
              AND tenant_id = %s
              AND publication_status = 'draft'
            RETURNING policy_version_id, tenant_id, scope_type, publication_status,
                      immutable_checksum
            """,
            (policy_version_id, self.tenant_context.tenant_id),
        )
        if row is None:
            raise RepositoryError("policy is missing, not a tenant draft, or already immutable")
        return row

    def _validate_tenant_scope(self, policy_version_id: str) -> None:
        self.assert_tenant(self.tenant_context.tenant_id)

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in {"draft", "published", "revoked"}:
            raise ValueError("policy publication status is invalid")


class PolicyDecisionRepository(TenantScopedRepository):
    """Append-only policy-decision storage with explicit policy scope."""

    def create(
        self,
        *,
        decision_id: str,
        case_id: str,
        proposal_id: str,
        policy_version_id: str,
        result: str,
        evaluated_conditions: Mapping[str, object],
        evaluator_version: str,
        decided_at: datetime,
        policy_scope_type: str = "tenant",
        policy_tenant_id: str | None = None,
    ) -> object:
        if policy_scope_type not in {"tenant", "global"}:
            raise ValueError("policy scope_type must be tenant or global")
        if result not in {"allow", "deny", "approval_required", "escalate"}:
            raise ValueError("policy result is outside the closed set")
        if policy_scope_type == "tenant":
            policy_tenant_id = self.tenant_context.tenant_id
        elif policy_tenant_id is not None:
            raise RepositoryError("global policy decisions cannot carry a tenant policy owner")
        row = self.fetch_one(
            """
            INSERT INTO public.policy_decisions (
                tenant_id, decision_id, case_id, proposal_id, policy_version_id,
                policy_scope_type, policy_tenant_id, result, evaluated_conditions,
                evaluator_version, decided_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING tenant_id, decision_id, case_id, proposal_id, policy_version_id,
                      policy_scope_type, policy_tenant_id, result, evaluated_conditions,
                      evaluator_version, decided_at
            """,
            (
                self.tenant_context.tenant_id,
                decision_id,
                case_id,
                proposal_id,
                policy_version_id,
                policy_scope_type,
                policy_tenant_id,
                result,
                _json(evaluated_conditions),
                evaluator_version,
                decided_at,
            ),
        )
        if row is None:
            raise RuntimeError("policy decision insert returned no row")
        return row

    persist = create
    append = create

    def get(self, *, decision_id: str) -> object | None:
        if not decision_id.strip():
            raise ValueError("decision_id is required")
        return self.fetch_one(
            """
            SELECT tenant_id, decision_id, case_id, proposal_id, policy_version_id,
                   policy_scope_type, policy_tenant_id, result, evaluated_conditions,
                   evaluator_version, decided_at
            FROM public.policy_decisions
            WHERE tenant_id = %s AND decision_id = %s
            """,
            (self.tenant_context.tenant_id, decision_id),
        )

    find = get

    def for_proposal(self, *, proposal_id: str) -> list[object]:
        if not proposal_id.strip():
            raise ValueError("proposal_id is required")
        return self.fetch_all(
            """
            SELECT tenant_id, decision_id, case_id, proposal_id, policy_version_id,
                   policy_scope_type, policy_tenant_id, result, evaluated_conditions,
                   evaluator_version, decided_at
            FROM public.policy_decisions
            WHERE tenant_id = %s AND proposal_id = %s
            ORDER BY decided_at, decision_id
            """,
            (self.tenant_context.tenant_id, proposal_id),
        )


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = ["PolicyDecisionRepository", "PolicyVersionRepository"]
