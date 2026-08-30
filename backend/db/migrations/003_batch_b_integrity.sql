-- Remediation Batch B: authoritative event provenance, policy scope/immutability,
-- and cross-aggregate relationship integrity.
--
-- PostgreSQL remains the authority.  Redpanda messages are accepted only after
-- an exact match to outbox_events; Neo4j never participates in authority.

-- The event schema version is part of the authoritative outbox identity.  Rows
-- created before this migration are the current 1.0.0 contract version.
ALTER TABLE outbox_events
    ADD COLUMN IF NOT EXISTS schema_version TEXT;

UPDATE outbox_events
SET schema_version = '1.0.0'
WHERE schema_version IS NULL;

ALTER TABLE outbox_events
    ALTER COLUMN schema_version SET DEFAULT '1.0.0';
ALTER TABLE outbox_events
    ALTER COLUMN schema_version SET NOT NULL;

-- A decision explicitly declares whether its policy reference is tenant-scoped
-- or centrally global.  policy_tenant_id is null only for an explicit global
-- reference; nullable scope is never inferred from a missing tenant match.
ALTER TABLE policy_decisions
    ADD COLUMN IF NOT EXISTS policy_scope_type TEXT;
ALTER TABLE policy_decisions
    ADD COLUMN IF NOT EXISTS policy_tenant_id TEXT;

UPDATE policy_decisions AS decision
SET policy_scope_type = policy.scope_type,
    policy_tenant_id = policy.tenant_id
FROM policy_versions AS policy
WHERE policy.policy_version_id = decision.policy_version_id
  AND (decision.policy_scope_type IS NULL OR decision.policy_tenant_id IS NULL);

UPDATE policy_decisions
SET policy_scope_type = 'tenant'
WHERE policy_scope_type IS NULL;

UPDATE policy_decisions
SET policy_tenant_id = tenant_id
WHERE policy_scope_type = 'tenant'
  AND policy_tenant_id IS NULL;

ALTER TABLE policy_decisions
    ALTER COLUMN policy_scope_type SET DEFAULT 'tenant';
ALTER TABLE policy_decisions
    ALTER COLUMN policy_scope_type SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_versions_scope_identity_key'
    ) THEN
        ALTER TABLE policy_versions
            ADD CONSTRAINT policy_versions_scope_identity_key
            UNIQUE (scope_type, policy_version_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_versions_tenant_identity_key'
    ) THEN
        ALTER TABLE policy_versions
            ADD CONSTRAINT policy_versions_tenant_identity_key
            UNIQUE (tenant_id, policy_version_id);
    END IF;
END;
$$;

ALTER TABLE policy_decisions
    DROP CONSTRAINT IF EXISTS policy_decisions_policy_version_id_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_scope_check'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_scope_check CHECK (
                (policy_scope_type = 'tenant' AND policy_tenant_id = tenant_id)
                OR (policy_scope_type = 'global' AND policy_tenant_id IS NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_tenant_policy_fkey'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_tenant_policy_fkey
            FOREIGN KEY (policy_tenant_id, policy_version_id)
            REFERENCES policy_versions (tenant_id, policy_version_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_scoped_policy_fkey'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_scoped_policy_fkey
            FOREIGN KEY (policy_scope_type, policy_version_id)
            REFERENCES policy_versions (scope_type, policy_version_id);
    END IF;
END;
$$;

-- The application tenant RLS policy may read centrally managed global policies,
-- but may only create tenant-scoped rows.  Global rows are centrally managed by
-- the privileged policy publication boundary, never by a tenant caller.
DROP POLICY IF EXISTS policy_versions_tenant_isolation ON policy_versions;
CREATE POLICY policy_versions_tenant_isolation ON policy_versions
    USING (tenant_id IS NULL OR tenant_id = reclaim.require_tenant_context())
    WITH CHECK (
        scope_type = 'tenant'
        AND tenant_id = reclaim.require_tenant_context()
    );

CREATE OR REPLACE FUNCTION reclaim_reject_published_policy_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.publication_status = 'published' THEN
        RAISE EXCEPTION 'published policy versions are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS policy_versions_published_immutable ON policy_versions;
CREATE TRIGGER policy_versions_published_immutable
    BEFORE UPDATE OR DELETE ON policy_versions
    FOR EACH ROW EXECUTE FUNCTION reclaim_reject_published_policy_mutation();

-- Decisions are historical interpretations.  Preventing mutation keeps their
-- resolved policy scope and version stable after later policy publication.
CREATE OR REPLACE FUNCTION reclaim_reject_policy_decision_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'policy decisions are append-only';
END;
$$;

DROP TRIGGER IF EXISTS policy_decisions_append_only ON policy_decisions;
CREATE TRIGGER policy_decisions_append_only
    BEFORE UPDATE OR DELETE ON policy_decisions
    FOR EACH ROW EXECUTE FUNCTION reclaim_reject_policy_decision_mutation();

-- Cross-aggregate identity targets.  The existing single-column FKs remain as
-- defense in depth; these composite unique constraints are the relationship
-- guarantees and can therefore be FK targets.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'action_proposals_case_identity_key'
    ) THEN
        ALTER TABLE action_proposals
            ADD CONSTRAINT action_proposals_case_identity_key
            UNIQUE (tenant_id, proposal_id, case_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_proposal_case_policy_key'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_proposal_case_policy_key
            UNIQUE (tenant_id, proposal_id, case_id, policy_version_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_identity_chain_key'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_identity_chain_key
            UNIQUE (tenant_id, decision_id, proposal_id, case_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'action_executions_case_identity_key'
    ) THEN
        ALTER TABLE action_executions
            ADD CONSTRAINT action_executions_case_identity_key
            UNIQUE (tenant_id, execution_id, case_id);
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_decisions_proposal_case_fkey'
    ) THEN
        ALTER TABLE policy_decisions
            ADD CONSTRAINT policy_decisions_proposal_case_fkey
            FOREIGN KEY (tenant_id, proposal_id, case_id)
            REFERENCES action_proposals (tenant_id, proposal_id, case_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approvals_decision_chain_fkey'
    ) THEN
        ALTER TABLE approvals
            ADD CONSTRAINT approvals_decision_chain_fkey
            FOREIGN KEY (tenant_id, proposal_id, case_id, policy_version_id)
            REFERENCES policy_decisions (
                tenant_id, proposal_id, case_id, policy_version_id
            );
    END IF;
END;
$$;

-- MAJOR-7: an execution must carry the approval that authorizes it when the
-- immutable policy decision requires approval.  The approval identity is
-- composite because an approval ID alone is not sufficient to prove tenant,
-- case, and proposal ownership.
ALTER TABLE action_executions
    ADD COLUMN IF NOT EXISTS approval_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approvals_execution_chain_key'
    ) THEN
        ALTER TABLE approvals
            ADD CONSTRAINT approvals_execution_chain_key
            UNIQUE (tenant_id, approval_id, proposal_id, case_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'action_executions_approval_chain_fkey'
    ) THEN
        ALTER TABLE action_executions
            ADD CONSTRAINT action_executions_approval_chain_fkey
            FOREIGN KEY (tenant_id, approval_id, proposal_id, case_id)
            REFERENCES approvals (tenant_id, approval_id, proposal_id, case_id);
    END IF;
END;
$$;

-- Action executions must identify the exact policy decision that authorized the
-- proposal.  Existing US1 development state has no execution rows; fail the
-- migration rather than weakening this invariant if an inconsistent database is
-- encountered.
ALTER TABLE action_executions
    ADD COLUMN IF NOT EXISTS policy_decision_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM action_executions
        WHERE policy_decision_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'cannot enforce action execution authorization: existing rows lack policy_decision_id';
    END IF;
END;
$$;

ALTER TABLE action_executions
    ALTER COLUMN policy_decision_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'action_executions_authorized_chain_fkey'
    ) THEN
        ALTER TABLE action_executions
            ADD CONSTRAINT action_executions_authorized_chain_fkey
            FOREIGN KEY (tenant_id, policy_decision_id, proposal_id, case_id)
            REFERENCES policy_decisions (
                tenant_id, decision_id, proposal_id, case_id
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verifications_execution_case_fkey'
    ) THEN
        ALTER TABLE verifications
            ADD CONSTRAINT verifications_execution_case_fkey
            FOREIGN KEY (tenant_id, execution_id, case_id)
            REFERENCES action_executions (tenant_id, execution_id, case_id);
    END IF;
END;
$$;

-- Conditional authorization cannot be represented by a foreign key alone:
-- allow may execute without approval, approval_required needs an exact live
-- approval, and deny/escalate must never execute.  This trigger is deliberately
-- invoker-security (not SECURITY DEFINER), so RLS remains active for the
-- tenant-scoped database role that performs the write.
CREATE OR REPLACE FUNCTION reclaim_validate_action_execution_authorization()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    decision_result TEXT;
    decision_policy_version_id TEXT;
    approval_policy_version_id TEXT;
    approval_status TEXT;
    approval_approved_at TIMESTAMPTZ;
    approval_expires_at TIMESTAMPTZ;
BEGIN
    SELECT result, policy_version_id
    INTO decision_result, decision_policy_version_id
    FROM policy_decisions
    WHERE tenant_id = NEW.tenant_id
      AND decision_id = NEW.policy_decision_id
      AND proposal_id = NEW.proposal_id
      AND case_id = NEW.case_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'action execution authorization decision does not match tenant, case, and proposal';
    END IF;

    IF decision_result IN ('deny', 'escalate') THEN
        RAISE EXCEPTION
            'policy decision result % cannot authorize action execution', decision_result;
    END IF;

    IF decision_result = 'approval_required' AND NEW.approval_id IS NULL THEN
        RAISE EXCEPTION
            'approval_required policy decision needs an approval before execution';
    END IF;

    IF NEW.approval_id IS NOT NULL THEN
        SELECT policy_version_id, status, approved_at, expires_at
        INTO approval_policy_version_id, approval_status,
             approval_approved_at, approval_expires_at
        FROM approvals
        WHERE tenant_id = NEW.tenant_id
          AND approval_id = NEW.approval_id
          AND proposal_id = NEW.proposal_id
          AND case_id = NEW.case_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'approval does not match execution tenant, case, and proposal';
        END IF;

        IF approval_policy_version_id <> decision_policy_version_id THEN
            RAISE EXCEPTION
                'approval does not reference the exact policy decision';
        END IF;

        IF approval_status <> 'approved' THEN
            RAISE EXCEPTION
                'approval status % cannot authorize action execution', approval_status;
        END IF;

        IF approval_approved_at > CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION 'approval is not effective yet';
        END IF;

        IF approval_expires_at IS NOT NULL
           AND approval_expires_at <= CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION 'approval has expired';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS action_executions_authorization_guard ON action_executions;
CREATE TRIGGER action_executions_authorization_guard
    BEFORE INSERT OR UPDATE OF tenant_id, case_id, proposal_id,
        policy_decision_id, approval_id ON action_executions
    FOR EACH ROW EXECUTE FUNCTION reclaim_validate_action_execution_authorization();

-- Do not leave pre-existing rows outside the new authorization invariant when
-- this migration is applied to a non-empty development database.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM action_executions AS execution
        JOIN policy_decisions AS decision
          ON decision.tenant_id = execution.tenant_id
         AND decision.decision_id = execution.policy_decision_id
         AND decision.proposal_id = execution.proposal_id
         AND decision.case_id = execution.case_id
        LEFT JOIN approvals AS approval
          ON approval.tenant_id = execution.tenant_id
         AND approval.approval_id = execution.approval_id
         AND approval.proposal_id = execution.proposal_id
         AND approval.case_id = execution.case_id
        WHERE decision.result IN ('deny', 'escalate')
           OR (
               decision.result = 'approval_required'
               AND (
                   execution.approval_id IS NULL
                   OR approval.status IS DISTINCT FROM 'approved'
                   OR approval.policy_version_id IS DISTINCT FROM decision.policy_version_id
                   OR approval.approved_at > CURRENT_TIMESTAMP
                   OR (
                       approval.expires_at IS NOT NULL
                       AND approval.expires_at <= CURRENT_TIMESTAMP
                   )
               )
           )
           OR (
               execution.approval_id IS NOT NULL
               AND (
                   approval.status IS DISTINCT FROM 'approved'
                   OR approval.policy_version_id IS DISTINCT FROM decision.policy_version_id
                   OR approval.approved_at > CURRENT_TIMESTAMP
                   OR (
                       approval.expires_at IS NOT NULL
                       AND approval.expires_at <= CURRENT_TIMESTAMP
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION
            'cannot enforce action execution authorization: existing rows violate policy or approval state';
    END IF;
END;
$$;
