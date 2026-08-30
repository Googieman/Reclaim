"""Unit checks for Batch B repository columns and explicit scope handling."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.actions import ActionExecutionRepository
from app.db.repositories.base import RepositoryError
from app.db.repositories.policy import PolicyDecisionRepository, PolicyVersionRepository
from app.db.tenant_context import TenantContext


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


class Cursor:
    def fetchone(self) -> tuple[object, ...]:
        return ("tenant-a", "identity", "proposal", "policy", "allow", NOW)


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, query: str, params: object = ()) -> Cursor:
        self.calls.append((query, params))
        return Cursor()


def context() -> TenantContext:
    principal = AuthenticatedPrincipal(
        subject="reclaim-event-relay",
        tenant_ids=frozenset({"tenant-a"}),
        tenant_roles={"tenant-a": frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return TenantContext.from_authorization_context(principal.for_tenant("tenant-a"))


def test_policy_decision_repository_writes_explicit_tenant_scope() -> None:
    connection = Connection()
    PolicyDecisionRepository(connection, context()).create(
        decision_id="decision-1",
        case_id="case-1",
        proposal_id="proposal-1",
        policy_version_id="policy-1",
        result="allow",
        evaluated_conditions={},
        evaluator_version="evaluator-1",
        decided_at=NOW,
    )

    query, params = connection.calls[0]
    assert "policy_scope_type" in query
    assert "policy_tenant_id" in query
    assert params[5:7] == ("tenant", "tenant-a")


def test_global_policy_version_cannot_be_created_by_tenant_scoped_repository() -> None:
    connection = Connection()
    repository = PolicyVersionRepository(connection, context())

    with pytest.raises(RepositoryError, match="centrally managed"):
        repository.create(
            policy_version_id="global-1",
            scope_type="global",
            thresholds={},
            action_allowlist=[],
            approval_rules={},
            effective_from=NOW,
            effective_to=None,
            author="policy-owner",
            publication_status="published",
            immutable_checksum="checksum",
        )

    assert connection.calls == []


def test_action_execution_repository_requires_policy_decision_identity() -> None:
    connection = Connection()
    ActionExecutionRepository(connection, context()).create(
        execution_id="execution-1",
        case_id="case-1",
        proposal_id="proposal-1",
        policy_decision_id="decision-1",
        approval_id="approval-1",
        connector_id="connector-1",
        idempotency_key="idempotency-1",
        request_checksum="checksum",
        status="received",
    )

    query, params = connection.calls[0]
    assert "policy_decision_id" in query
    assert "approval_id" in query
    assert params[4] == "decision-1"
    assert params[5] == "approval-1"


def test_batch_b_migration_declares_all_database_invariants() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "backend/db/migrations/003_batch_b_integrity.sql").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "schema_version",
        "policy_decisions_scope_check",
        "policy_decisions_tenant_policy_fkey",
        "policy_versions_published_immutable",
        "approvals_decision_chain_fkey",
        "action_executions_authorized_chain_fkey",
        "action_executions_approval_chain_fkey",
        "action_executions_authorization_guard",
        "verifications_execution_case_fkey",
    ):
        assert fragment in migration
