"""Live PostgreSQL adversarial checks for Remediation Batch B."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("RECLAIM_DATABASE_URL")
    if not value:
        pytest.skip(
            "RECLAIM_DATABASE_URL is required for live Batch B PostgreSQL validation"
        )
    return value


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_a: str
    tenant_b: str
    case_a: str
    case_a_other: str
    case_b: str
    policy_a: str
    policy_b: str
    policy_global: str
    policy_published: str
    policy_draft: str
    proposal_a: str
    proposal_other: str
    decision_a: str
    decision_other: str
    approval_a: str
    execution_a: str


@pytest.fixture
def seeded_connection():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(_database_url())
    seed = _seed(connection)
    try:
        yield connection, seed
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def committed_rls_seed():
    """Commit isolated data so a separate non-owner connection can observe RLS."""

    psycopg = pytest.importorskip("psycopg")
    if not os.getenv("RECLAIM_RLS_DATABASE_URL"):
        pytest.skip("RECLAIM_RLS_DATABASE_URL is required for non-owner RLS validation")

    owner = psycopg.connect(_database_url())
    seed = _seed(owner)
    _set_tenant(owner, seed.tenant_b)
    rls_proposal, rls_decision = _authorization_target(
        owner,
        seed.tenant_b,
        seed.case_b,
        seed.policy_b,
        "approval_required",
        "rls-tenant-b",
    )
    rls_approval = f"major7-rls-approval-{uuid4().hex}"
    _insert_approval(
        owner, seed.tenant_b, rls_approval, seed.case_b, rls_proposal, seed.policy_b
    )
    _insert_execution(
        owner,
        seed.tenant_b,
        f"major7-rls-execution-{uuid4().hex}",
        seed.case_b,
        rls_proposal,
        rls_decision,
        rls_approval,
    )
    owner.commit()
    owner.close()

    try:
        yield seed
    finally:
        cleanup = psycopg.connect(_database_url())
        tenant_ids = (seed.tenant_a, seed.tenant_b)
        cleanup.execute(
            "DELETE FROM verifications WHERE tenant_id IN (%s, %s)", tenant_ids
        )
        cleanup.execute(
            "DELETE FROM action_executions WHERE tenant_id IN (%s, %s)", tenant_ids
        )
        cleanup.execute("DELETE FROM approvals WHERE tenant_id IN (%s, %s)", tenant_ids)
        cleanup.execute(
            "ALTER TABLE policy_decisions DISABLE TRIGGER policy_decisions_append_only"
        )
        cleanup.execute(
            "DELETE FROM policy_decisions WHERE tenant_id IN (%s, %s)", tenant_ids
        )
        cleanup.execute(
            "ALTER TABLE policy_decisions ENABLE TRIGGER policy_decisions_append_only"
        )
        cleanup.execute(
            "DELETE FROM action_proposals WHERE tenant_id IN (%s, %s)", tenant_ids
        )
        cleanup.execute("DELETE FROM cases WHERE tenant_id IN (%s, %s)", tenant_ids)
        cleanup.execute("DELETE FROM incidents WHERE tenant_id IN (%s, %s)", tenant_ids)
        cleanup.execute(
            "ALTER TABLE policy_versions DISABLE TRIGGER policy_versions_published_immutable"
        )
        cleanup.execute(
            "DELETE FROM policy_versions WHERE policy_version_id IN (%s, %s, %s, %s, %s, %s)",
            (
                seed.policy_a,
                seed.policy_b,
                seed.policy_global,
                seed.policy_published,
                seed.policy_draft,
                # The RLS fixture creates no additional global policy version.
                seed.policy_global,
            ),
        )
        cleanup.execute(
            "ALTER TABLE policy_versions ENABLE TRIGGER policy_versions_published_immutable"
        )
        cleanup.execute("DELETE FROM tenants WHERE tenant_id IN (%s, %s)", tenant_ids)
        cleanup.commit()
        cleanup.close()


def _seed(connection) -> Seed:
    suffix = uuid4().hex
    tenant_a = f"batch-b-a-{suffix}"
    tenant_b = f"batch-b-b-{suffix}"
    case_a = f"case-a-{suffix}"
    case_a_other = f"case-a-other-{suffix}"
    case_b = f"case-b-{suffix}"
    policy_a = f"policy-a-{suffix}"
    policy_b = f"policy-b-{suffix}"
    policy_global = f"policy-global-{suffix}"
    policy_published = f"policy-published-{suffix}"
    policy_draft = f"policy-draft-{suffix}"
    proposal_a = f"proposal-a-{suffix}"
    proposal_other = f"proposal-other-{suffix}"
    decision_a = f"decision-a-{suffix}"
    decision_other = f"decision-other-{suffix}"
    approval_a = f"approval-a-{suffix}"
    execution_a = f"execution-a-{suffix}"

    _set_tenant(connection, tenant_a)
    connection.execute(
        "INSERT INTO tenants (tenant_id, display_name) VALUES (%s, %s)",
        (tenant_a, "Batch B Tenant A"),
    )
    connection.execute(
        "INSERT INTO incidents (tenant_id, incident_id, source, received_at, correlation_key, intake_status, deduplication_identity) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)",
        (
            tenant_a,
            f"incident-a-{suffix}",
            "test",
            NOW,
            f"corr-a-{suffix}",
            f"dedupe-a-{suffix}",
        ),
    )
    incident_a = f"incident-a-{suffix}"
    _insert_case(connection, tenant_a, case_a, incident_a)
    incident_a_other = f"incident-a-other-{suffix}"
    connection.execute(
        "INSERT INTO incidents (tenant_id, incident_id, source, received_at, correlation_key, intake_status, deduplication_identity) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)",
        (
            tenant_a,
            incident_a_other,
            "test",
            NOW,
            f"corr-a-other-{suffix}",
            f"dedupe-a-other-{suffix}",
        ),
    )
    _insert_case(connection, tenant_a, case_a_other, incident_a_other)

    _set_tenant(connection, tenant_b)
    connection.execute(
        "INSERT INTO tenants (tenant_id, display_name) VALUES (%s, %s)",
        (tenant_b, "Batch B Tenant B"),
    )
    incident_b = f"incident-b-{suffix}"
    connection.execute(
        "INSERT INTO incidents (tenant_id, incident_id, source, received_at, correlation_key, intake_status, deduplication_identity) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)",
        (tenant_b, incident_b, "test", NOW, f"corr-b-{suffix}", f"dedupe-b-{suffix}"),
    )
    _insert_case(connection, tenant_b, case_b, incident_b)
    _insert_policy(connection, tenant_b, policy_b, "tenant", "draft")

    _set_tenant(connection, tenant_a)
    _insert_policy(connection, tenant_a, policy_a, "tenant", "published")
    _insert_policy(connection, tenant_a, policy_published, "tenant", "published")
    _insert_policy(connection, tenant_a, policy_draft, "tenant", "draft")
    _insert_policy(connection, None, policy_global, "global", "published")
    _insert_proposal(connection, tenant_a, proposal_a, case_a)
    _insert_proposal(connection, tenant_a, proposal_other, case_a_other)
    _insert_decision(
        connection,
        tenant_a,
        decision_a,
        case_a,
        proposal_a,
        policy_a,
        "tenant",
        tenant_a,
    )
    _insert_decision(
        connection,
        tenant_a,
        decision_other,
        case_a_other,
        proposal_other,
        policy_a,
        "tenant",
        tenant_a,
    )
    connection.execute(
        """
        INSERT INTO approvals (
            tenant_id, approval_id, case_id, proposal_id, approver_id, approver_role,
            proposer_id, scope, policy_version_id, status, approved_at,
            separation_of_duties_evidence
        ) VALUES (%s, %s, %s, %s, 'approver-a', 'approver', 'proposer-a',
                  'refund', %s, 'approved', %s, 'distinct authenticated principals')
        """,
        (tenant_a, approval_a, case_a, proposal_a, policy_a, NOW),
    )
    connection.execute(
        """
        INSERT INTO action_executions (
            tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
            connector_id, idempotency_key, request_checksum, status
        ) VALUES (%s, %s, %s, %s, %s, 'test-action', %s, 'checksum', 'received')
        """,
        (tenant_a, execution_a, case_a, proposal_a, decision_a, f"action-{suffix}"),
    )
    connection.execute(
        """
        INSERT INTO verifications (
            tenant_id, verification_id, execution_id, case_id, observed_resource_state,
            verifier_source, result, verified_at
        ) VALUES (%s, %s, %s, %s, 'revoked', 'test-verifier', 'verified_success', %s)
        """,
        (tenant_a, f"verification-a-{suffix}", execution_a, case_a, NOW),
    )

    return Seed(
        tenant_a,
        tenant_b,
        case_a,
        case_a_other,
        case_b,
        policy_a,
        policy_b,
        policy_global,
        policy_published,
        policy_draft,
        proposal_a,
        proposal_other,
        decision_a,
        decision_other,
        approval_a,
        execution_a,
    )


def _set_tenant(connection, tenant_id: str) -> None:
    connection.execute(
        "SELECT set_config('reclaim.tenant_id', %s, true)", (tenant_id or "",)
    )


def _insert_case(connection, tenant_id: str, case_id: str, incident_id: str) -> None:
    connection.execute(
        "INSERT INTO cases (tenant_id, case_id, incident_id, current_state) VALUES (%s, %s, %s, 'timeline_ready')",
        (tenant_id, case_id, incident_id),
    )


def _insert_policy(
    connection, tenant_id: str | None, policy_id: str, scope: str, status: str
) -> None:
    connection.execute(
        """
        INSERT INTO policy_versions (
            policy_version_id, tenant_id, scope_type, thresholds, action_allowlist,
            approval_rules, effective_from, author, publication_status, immutable_checksum
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s,
                  'policy-owner', %s, %s)
        """,
        (
            policy_id,
            tenant_id,
            scope,
            json.dumps({"maximum": 100}),
            json.dumps(["revoke_suspicious_session"]),
            json.dumps({"refund_payment": "approval"}),
            NOW,
            status,
            f"checksum-{policy_id}",
        ),
    )


def _insert_proposal(
    connection, tenant_id: str, proposal_id: str, case_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO action_proposals (
            tenant_id, proposal_id, case_id, action_type, target_resource,
            rationale, idempotency_key, analysis_id
        ) VALUES (%s, %s, %s, 'revoke_suspicious_session', 'session-1',
                  'test proposal', %s, 'analysis-1')
        """,
        (tenant_id, proposal_id, case_id, f"idempotency-{proposal_id}"),
    )


def _insert_decision(
    connection,
    tenant_id: str,
    decision_id: str,
    case_id: str,
    proposal_id: str,
    policy_id: str,
    scope: str,
    policy_tenant_id: str | None,
    result: str = "allow",
) -> None:
    connection.execute(
        """
        INSERT INTO policy_decisions (
            tenant_id, decision_id, case_id, proposal_id, policy_version_id,
            policy_scope_type, policy_tenant_id, result, evaluator_version, decided_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'batch-b-test', %s)
        """,
        (
            tenant_id,
            decision_id,
            case_id,
            proposal_id,
            policy_id,
            scope,
            policy_tenant_id,
            result,
            NOW,
        ),
    )


def _insert_approval(
    connection,
    tenant_id: str,
    approval_id: str,
    case_id: str,
    proposal_id: str,
    policy_id: str,
    status: str = "approved",
    expires_at=None,
) -> None:
    connection.execute(
        """
        INSERT INTO approvals (
            tenant_id, approval_id, case_id, proposal_id, approver_id, approver_role,
            proposer_id, scope, policy_version_id, status, approved_at, expires_at,
            separation_of_duties_evidence
        ) VALUES (%s, %s, %s, %s, 'approver', 'approver', 'proposer', 'test-action',
                  %s, %s, CURRENT_TIMESTAMP - INTERVAL '1 minute', %s,
                  'distinct authenticated principals')
        """,
        (tenant_id, approval_id, case_id, proposal_id, policy_id, status, expires_at),
    )


def _insert_execution(
    connection,
    tenant_id: str,
    execution_id: str,
    case_id: str,
    proposal_id: str,
    decision_id: str,
    approval_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO action_executions (
            tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
            approval_id, connector_id, idempotency_key, request_checksum, status
        ) VALUES (%s, %s, %s, %s, %s, %s, 'test-action', %s, 'checksum', 'received')
        """,
        (
            tenant_id,
            execution_id,
            case_id,
            proposal_id,
            decision_id,
            approval_id,
            f"idempotency-{execution_id}",
        ),
    )


def _assert_execution_rejected(
    connection,
    tenant_id: str,
    execution_id: str,
    case_id: str,
    proposal_id: str,
    decision_id: str,
    approval_id: str | None = None,
) -> None:
    _assert_rejected(
        connection,
        """
        INSERT INTO action_executions (
            tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
            approval_id, connector_id, idempotency_key, request_checksum, status
        ) VALUES (%s, %s, %s, %s, %s, %s, 'test-action', %s, 'checksum', 'received')
        """,
        (
            tenant_id,
            execution_id,
            case_id,
            proposal_id,
            decision_id,
            approval_id,
            f"idempotency-{execution_id}",
        ),
    )


def _authorization_target(
    connection,
    tenant_id: str,
    case_id: str,
    policy_id: str,
    result: str,
    label: str,
) -> tuple[str, str]:
    proposal_id = f"major7-proposal-{label}-{uuid4().hex}"
    decision_id = f"major7-decision-{label}-{uuid4().hex}"
    _insert_proposal(connection, tenant_id, proposal_id, case_id)
    _insert_decision(
        connection,
        tenant_id,
        decision_id,
        case_id,
        proposal_id,
        policy_id,
        "tenant",
        tenant_id,
        result,
    )
    return proposal_id, decision_id


def _assert_rejected(connection, query: str, params: tuple[object, ...]) -> None:
    psycopg = pytest.importorskip("psycopg")
    connection.execute("SAVEPOINT batch_b_violation")
    try:
        with pytest.raises(psycopg.Error):
            connection.execute(query, params)
    finally:
        connection.execute("ROLLBACK TO SAVEPOINT batch_b_violation")
        connection.execute("RELEASE SAVEPOINT batch_b_violation")


def test_live_policy_scope_and_publication_immutability(seeded_connection) -> None:
    connection, seed = seeded_connection

    _assert_rejected(
        connection,
        """
        INSERT INTO policy_decisions (
            tenant_id, decision_id, case_id, proposal_id, policy_version_id,
            policy_scope_type, policy_tenant_id, result, evaluator_version, decided_at
        ) VALUES (%s, 'decision-cross-tenant', %s, %s, %s, 'tenant', %s,
                  'allow', 'batch-b-test', %s)
        """,
        (
            seed.tenant_a,
            seed.case_a,
            seed.proposal_a,
            seed.policy_b,
            seed.tenant_a,
            NOW,
        ),
    )

    connection.execute(
        """
        INSERT INTO action_proposals (
            tenant_id, proposal_id, case_id, action_type, target_resource,
            rationale, idempotency_key, analysis_id
        ) VALUES (%s, 'proposal-global', %s, 'revoke_suspicious_session', 'session-2',
                  'global policy test', 'idempotency-global', 'analysis-global')
        """,
        (seed.tenant_a, seed.case_a),
    )
    connection.execute(
        """
        INSERT INTO policy_decisions (
            tenant_id, decision_id, case_id, proposal_id, policy_version_id,
            policy_scope_type, policy_tenant_id, result, evaluator_version, decided_at
        ) VALUES (%s, 'decision-global', %s, 'proposal-global', %s, 'global', NULL,
                  'allow', 'batch-b-test', %s)
        """,
        (seed.tenant_a, seed.case_a, seed.policy_global, NOW),
    )

    connection.execute(
        "UPDATE policy_versions SET thresholds = %s::jsonb WHERE policy_version_id = %s",
        (json.dumps({"maximum": 1}), seed.policy_draft),
    )
    _assert_rejected(
        connection,
        "UPDATE policy_versions SET thresholds = %s::jsonb WHERE policy_version_id = %s",
        (json.dumps({"maximum": 1}), seed.policy_published),
    )
    _assert_rejected(
        connection,
        "UPDATE policy_versions SET approval_rules = %s::jsonb WHERE policy_version_id = %s",
        (json.dumps({"refund_payment": "none"}), seed.policy_published),
    )
    _assert_rejected(
        connection,
        "DELETE FROM policy_versions WHERE policy_version_id = %s",
        (seed.policy_published,),
    )
    _assert_rejected(
        connection,
        "UPDATE policy_decisions SET result = 'deny' WHERE decision_id = %s",
        (seed.decision_a,),
    )

    resolved = connection.execute(
        """
        SELECT decision.policy_version_id, policy.immutable_checksum
        FROM policy_decisions AS decision
        JOIN policy_versions AS policy
          ON policy.policy_version_id = decision.policy_version_id
        WHERE decision.tenant_id = %s AND decision.decision_id = %s
        """,
        (seed.tenant_a, seed.decision_a),
    ).fetchone()
    assert resolved == (seed.policy_a, f"checksum-{seed.policy_a}")


def test_live_cross_aggregate_chain_rejects_direct_inconsistent_writes(
    seeded_connection,
) -> None:
    connection, seed = seeded_connection

    _assert_rejected(
        connection,
        """
        INSERT INTO action_proposals (
            tenant_id, proposal_id, case_id, action_type, target_resource,
            rationale, idempotency_key, analysis_id
        ) VALUES (%s, 'proposal-case-cross', %s, 'revoke_suspicious_session', 'session-3',
                  'cross-tenant proposal', 'idempotency-case-cross', 'analysis-case-cross')
        """,
        (seed.tenant_a, seed.case_b),
    )

    _assert_rejected(
        connection,
        """
        INSERT INTO approvals (
            tenant_id, approval_id, case_id, proposal_id, approver_id, approver_role,
            proposer_id, scope, policy_version_id, status, approved_at,
            separation_of_duties_evidence
        ) VALUES (%s, 'approval-chain-cross', %s, %s, 'approver-b', 'approver',
                  'proposer-a', 'refund', %s, 'approved', %s, 'distinct principals')
        """,
        (seed.tenant_a, seed.case_a, seed.proposal_other, seed.policy_a, NOW),
    )

    _assert_rejected(
        connection,
        """
        INSERT INTO action_executions (
            tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
            connector_id, idempotency_key, request_checksum, status
        ) VALUES (%s, 'execution-chain-cross', %s, %s, %s, 'test-action',
                  'idempotency-execution-cross', 'checksum', 'received')
        """,
        (seed.tenant_a, seed.case_a, seed.proposal_other, seed.decision_other),
    )

    _assert_rejected(
        connection,
        """
        INSERT INTO verifications (
            tenant_id, verification_id, execution_id, case_id, observed_resource_state,
            verifier_source, result, verified_at
        ) VALUES (%s, 'verification-chain-cross', %s, %s, 'unknown', 'test-verifier',
                  'verified_success', %s)
        """,
        (seed.tenant_a, seed.execution_a, seed.case_a_other, NOW),
    )

    _set_tenant(connection, seed.tenant_b)
    _assert_rejected(
        connection,
        """
        INSERT INTO action_executions (
            tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
            connector_id, idempotency_key, request_checksum, status
        ) VALUES (%s, 'execution-tenant-cross', %s, %s, %s, 'test-action',
                  'idempotency-tenant-cross', 'checksum', 'received')
        """,
        (seed.tenant_b, seed.case_b, seed.proposal_a, seed.decision_a),
    )
    _set_tenant(connection, seed.tenant_a)

    valid = connection.execute(
        """
        SELECT count(*) FROM verifications
        WHERE tenant_id = %s AND execution_id = %s AND case_id = %s
        """,
        (seed.tenant_a, seed.execution_a, seed.case_a),
    ).fetchone()
    assert valid == (1,)


def test_live_major7_policy_result_and_approval_matrix(seeded_connection) -> None:
    """Direct SQL proves policy-to-execution authorization at the database boundary."""

    connection, seed = seeded_connection

    # A. approval_required without an approval is rejected.
    proposal, decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "no-approval",
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-a-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
    )

    # B. The approved contract has no pending status.  An attempted pending row
    # and an execution referring to it are both rejected.
    proposal, decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "pending",
    )
    pending_id = f"major7-pending-{uuid4().hex}"
    _assert_rejected(
        connection,
        """
        INSERT INTO approvals (
            tenant_id, approval_id, case_id, proposal_id, approver_id, approver_role,
            proposer_id, scope, policy_version_id, status, approved_at,
            separation_of_duties_evidence
        ) VALUES (%s, %s, %s, %s, 'approver', 'approver', 'proposer', 'test-action', %s,
                  'pending', CURRENT_TIMESTAMP - INTERVAL '1 minute',
                  'distinct authenticated principals')
        """,
        (seed.tenant_a, pending_id, seed.case_a, proposal, seed.policy_a),
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-b-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
        pending_id,
    )

    # C. A rejected approval cannot authorize execution.
    proposal, decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "rejected",
    )
    approval = f"major7-rejected-{uuid4().hex}"
    _insert_approval(
        connection,
        seed.tenant_a,
        approval,
        seed.case_a,
        proposal,
        seed.policy_a,
        "rejected",
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-c-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
        approval,
    )

    # C2. An expired approval cannot authorize execution.
    proposal, decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "expired",
    )
    approval = f"major7-expired-{uuid4().hex}"
    _insert_approval(
        connection,
        seed.tenant_a,
        approval,
        seed.case_a,
        proposal,
        seed.policy_a,
        "expired",
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-c2-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
        approval,
    )

    # D. An approved authorization for another proposal cannot be reused.
    target_proposal, target_decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "other-proposal-target",
    )
    other_proposal, _ = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "other-proposal",
    )
    other_approval = f"major7-other-proposal-approval-{uuid4().hex}"
    _insert_approval(
        connection,
        seed.tenant_a,
        other_approval,
        seed.case_a,
        other_proposal,
        seed.policy_a,
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-d-{uuid4().hex}",
        seed.case_a,
        target_proposal,
        target_decision,
        other_approval,
    )
    # E. An approved authorization for another case cannot be reused.
    target_proposal, target_decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "other-case-target",
    )
    other_proposal, _ = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a_other,
        seed.policy_a,
        "approval_required",
        "other-case",
    )
    other_approval = f"major7-other-case-approval-{uuid4().hex}"
    _insert_approval(
        connection,
        seed.tenant_a,
        other_approval,
        seed.case_a_other,
        other_proposal,
        seed.policy_a,
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-e-{uuid4().hex}",
        seed.case_a,
        target_proposal,
        target_decision,
        other_approval,
    )
    # F. An approved authorization from another tenant cannot be reused.
    target_proposal, target_decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "other-tenant-target",
    )
    _set_tenant(connection, seed.tenant_b)
    other_proposal, _ = _authorization_target(
        connection,
        seed.tenant_b,
        seed.case_b,
        seed.policy_b,
        "approval_required",
        "other-tenant",
    )
    other_approval = f"major7-other-tenant-approval-{uuid4().hex}"
    _insert_approval(
        connection,
        seed.tenant_b,
        other_approval,
        seed.case_b,
        other_proposal,
        seed.policy_b,
    )
    _set_tenant(connection, seed.tenant_a)
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-f-{uuid4().hex}",
        seed.case_a,
        target_proposal,
        target_decision,
        other_approval,
    )
    # G. Deny is terminal for authorization, even without an approval.
    proposal, decision = _authorization_target(
        connection, seed.tenant_a, seed.case_a, seed.policy_a, "deny", "deny"
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-g-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
    )

    # H. An explicit allow is auto-executable without human approval.
    proposal, decision = _authorization_target(
        connection, seed.tenant_a, seed.case_a, seed.policy_a, "allow", "allow"
    )
    execution_allow = f"major7-execution-h-{uuid4().hex}"
    _insert_execution(
        connection, seed.tenant_a, execution_allow, seed.case_a, proposal, decision
    )

    # H2. An existing execution cannot be retargeted to a denying decision.
    deny_proposal, deny_decision = _authorization_target(
        connection, seed.tenant_a, seed.case_a, seed.policy_a, "deny", "update-deny"
    )
    _assert_rejected(
        connection,
        """
        UPDATE action_executions
        SET proposal_id = %s, policy_decision_id = %s
        WHERE tenant_id = %s AND execution_id = %s
        """,
        (deny_proposal, deny_decision, seed.tenant_a, execution_allow),
    )

    # I. approval_required succeeds only with the exact current approved record.
    proposal, decision = _authorization_target(
        connection,
        seed.tenant_a,
        seed.case_a,
        seed.policy_a,
        "approval_required",
        "exact",
    )
    approval = f"major7-exact-approval-{uuid4().hex}"
    _insert_approval(
        connection, seed.tenant_a, approval, seed.case_a, proposal, seed.policy_a
    )
    execution_exact = f"major7-execution-i-{uuid4().hex}"
    _insert_execution(
        connection,
        seed.tenant_a,
        execution_exact,
        seed.case_a,
        proposal,
        decision,
        approval,
    )

    # J. Verification remains bound to the same execution/case chain.
    _assert_rejected(
        connection,
        """
        INSERT INTO verifications (
            tenant_id, verification_id, execution_id, case_id, observed_resource_state,
            verifier_source, result, verified_at
        ) VALUES (%s, %s, %s, %s, 'unknown', 'test-verifier', 'verified_success', %s)
        """,
        (
            seed.tenant_a,
            f"major7-verification-j-{uuid4().hex}",
            execution_allow,
            seed.case_a_other,
            NOW,
        ),
    )

    # K. Escalation is not an executable policy result.
    proposal, decision = _authorization_target(
        connection, seed.tenant_a, seed.case_a, seed.policy_a, "escalate", "escalate"
    )
    _assert_execution_rejected(
        connection,
        seed.tenant_a,
        f"major7-execution-k-{uuid4().hex}",
        seed.case_a,
        proposal,
        decision,
    )


def test_live_major7_non_owner_rls_policy_and_action_isolation(
    committed_rls_seed,
) -> None:
    """A non-owner tenant context sees global plus own policy data only."""

    psycopg = pytest.importorskip("psycopg")
    seed = committed_rls_seed
    connection = psycopg.connect(os.environ["RECLAIM_RLS_DATABASE_URL"])
    try:
        _set_tenant(connection, seed.tenant_a)
        visible_policies = connection.execute(
            """
            SELECT policy_version_id, tenant_id
            FROM policy_versions
            WHERE policy_version_id IN (%s, %s, %s)
            ORDER BY policy_version_id
            """,
            (seed.policy_a, seed.policy_b, seed.policy_global),
        ).fetchall()
        assert visible_policies == sorted(
            [(seed.policy_a, seed.tenant_a), (seed.policy_global, None)]
        )
        assert connection.execute(
            "SELECT count(*) FROM approvals WHERE tenant_id = %s", (seed.tenant_b,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM action_executions WHERE tenant_id = %s",
            (seed.tenant_b,),
        ).fetchone() == (0,)

        _assert_rejected(
            connection,
            """
            INSERT INTO policy_versions (
                policy_version_id, tenant_id, scope_type, effective_from,
                author, publication_status, immutable_checksum
            ) VALUES (%s, %s, 'tenant', CURRENT_TIMESTAMP, 'attacker', 'draft', 'bad')
            """,
            (f"major7-rls-policy-{uuid4().hex}", seed.tenant_b),
        )
        _assert_rejected(
            connection,
            """
            INSERT INTO approvals (
                tenant_id, approval_id, case_id, proposal_id, approver_id, approver_role,
                proposer_id, scope, policy_version_id, status, approved_at,
                separation_of_duties_evidence
            ) VALUES (%s, %s, %s, %s, 'approver', 'approver', 'proposer', 'test-action',
                      %s, 'approved', CURRENT_TIMESTAMP - INTERVAL '1 minute', 'distinct')
            """,
            (
                seed.tenant_b,
                f"major7-rls-approval-write-{uuid4().hex}",
                seed.case_b,
                "not-visible-proposal",
                seed.policy_b,
            ),
        )
        _assert_rejected(
            connection,
            """
            INSERT INTO action_executions (
                tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                approval_id, connector_id, idempotency_key, request_checksum, status
            ) VALUES (%s, %s, %s, %s, %s, %s, 'test-action', %s, 'checksum', 'received')
            """,
            (
                seed.tenant_b,
                f"major7-rls-execution-write-{uuid4().hex}",
                seed.case_b,
                "not-visible-proposal",
                "not-visible-decision",
                "not-visible-approval",
                f"major7-rls-idempotency-{uuid4().hex}",
            ),
        )
    finally:
        connection.close()
