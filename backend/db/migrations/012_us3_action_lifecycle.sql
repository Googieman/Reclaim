-- US3 T095-T098: durable action lifecycle, merchant verification, escalation,
-- and explicit terminal-outcome provenance.
--
-- This migration is additive and idempotent.  Existing action, verification, or
-- escalation rows do not contain enough authoritative data to infer canonical
-- identity, resource binding, provider retry identity, or provenance.  Refuse
-- the upgrade rather than inventing security-critical history.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'action_executions'
          AND column_name = 'canonical_action_id'
    ) AND EXISTS (SELECT 1 FROM public.action_executions) THEN
        RAISE EXCEPTION
            'migration 012 cannot safely infer canonical action identity for historical action executions';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'verifications'
          AND column_name = 'canonical_action_id'
    ) AND EXISTS (SELECT 1 FROM public.verifications) THEN
        RAISE EXCEPTION
            'migration 012 cannot safely infer canonical action identity for historical verifications';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'escalations'
          AND column_name = 'currency'
    ) AND EXISTS (SELECT 1 FROM public.escalations) THEN
        RAISE EXCEPTION
            'migration 012 cannot safely infer currency and lifecycle provenance for historical escalations';
    END IF;
END;
$$;

ALTER TABLE public.action_executions
    ADD COLUMN IF NOT EXISTS canonical_action_id TEXT,
    ADD COLUMN IF NOT EXISTS resource_type TEXT,
    ADD COLUMN IF NOT EXISTS target_resource TEXT,
    ADD COLUMN IF NOT EXISTS provider_idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS reconciliation_state TEXT,
    ADD COLUMN IF NOT EXISTS last_remote_result TEXT,
    ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT;

ALTER TABLE public.verifications
    ADD COLUMN IF NOT EXISTS canonical_action_id TEXT,
    ADD COLUMN IF NOT EXISTS resource_type TEXT,
    ADD COLUMN IF NOT EXISTS target_resource TEXT,
    ADD COLUMN IF NOT EXISTS connector_id TEXT,
    ADD COLUMN IF NOT EXISTS verification_method TEXT,
    ADD COLUMN IF NOT EXISTS verification_version TEXT,
    ADD COLUMN IF NOT EXISTS state_checksum TEXT;

ALTER TABLE public.escalations
    ADD COLUMN IF NOT EXISTS owner_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS currency CHAR(3),
    ADD COLUMN IF NOT EXISTS canonical_action_id TEXT,
    ADD COLUMN IF NOT EXISTS execution_id TEXT,
    ADD COLUMN IF NOT EXISTS verification_id TEXT,
    ADD COLUMN IF NOT EXISTS policy_version_id TEXT,
    ADD COLUMN IF NOT EXISTS action_version TEXT,
    ADD COLUMN IF NOT EXISTS verification_version TEXT,
    ADD COLUMN IF NOT EXISTS checksum TEXT,
    ADD COLUMN IF NOT EXISTS version INTEGER,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT;

-- Empty historical tables take the safe defaults.  On a partially applied
-- migration, NOT NULL below fails if any row is incomplete.
ALTER TABLE public.action_executions
    ALTER COLUMN canonical_action_id SET NOT NULL,
    ALTER COLUMN resource_type SET NOT NULL,
    ALTER COLUMN target_resource SET NOT NULL,
    ALTER COLUMN connector_id SET NOT NULL,
    ALTER COLUMN provider_idempotency_key SET NOT NULL,
    ALTER COLUMN reconciliation_state SET DEFAULT 'not_required',
    ALTER COLUMN reconciliation_state SET NOT NULL,
    ALTER COLUMN correlation_id SET NOT NULL;
ALTER TABLE public.verifications
    ALTER COLUMN canonical_action_id SET NOT NULL,
    ALTER COLUMN resource_type SET NOT NULL,
    ALTER COLUMN target_resource SET NOT NULL,
    ALTER COLUMN verification_method SET DEFAULT 'merchant_state_read',
    ALTER COLUMN verification_method SET NOT NULL,
    ALTER COLUMN verification_version SET DEFAULT 'verification-v1.0.0',
    ALTER COLUMN verification_version SET NOT NULL,
    ALTER COLUMN state_checksum SET NOT NULL;
ALTER TABLE public.escalations
    ALTER COLUMN owner_tenant_id SET NOT NULL,
    ALTER COLUMN currency SET NOT NULL,
    ALTER COLUMN action_version SET DEFAULT 'action-idempotency-v1.0.0',
    ALTER COLUMN action_version SET NOT NULL,
    ALTER COLUMN version SET DEFAULT 0,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_canonical_identity_check'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_canonical_identity_check
            CHECK (canonical_action_id ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_resource_identity_nonblank'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_resource_identity_nonblank
            CHECK (length(btrim(resource_type)) > 0 AND length(btrim(target_resource)) > 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_reconciliation_state_check'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_reconciliation_state_check
            CHECK (reconciliation_state IN ('not_required', 'required', 'in_progress', 'resolved', 'unresolved'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_unknown_reconciliation_check'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_unknown_reconciliation_check
            CHECK (status <> 'unknown' OR reconciliation_state IN ('required', 'in_progress', 'unresolved'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_remote_result_check'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_remote_result_check
            CHECK (last_remote_result IS NULL OR last_remote_result IN ('accepted', 'submitted', 'completed', 'succeeded', 'rejected', 'failed', 'unknown'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.verifications'::regclass
          AND conname = 'verifications_identity_nonblank'
    ) THEN
        ALTER TABLE public.verifications
            ADD CONSTRAINT verifications_identity_nonblank
            CHECK (
                length(btrim(canonical_action_id)) > 0
                AND length(btrim(resource_type)) > 0
                AND length(btrim(target_resource)) > 0
                AND length(btrim(connector_id)) > 0
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.verifications'::regclass
          AND conname = 'verifications_state_checksum_check'
    ) THEN
        ALTER TABLE public.verifications
            ADD CONSTRAINT verifications_state_checksum_check
            CHECK (state_checksum ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_owner_tenant_check'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_owner_tenant_check
            CHECK (owner_tenant_id = tenant_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_currency_check'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_currency_check
            CHECK (currency = upper(currency) AND length(currency) = 3);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_version_nonnegative'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_version_nonnegative CHECK (version >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_execution_requires_action'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_execution_requires_action
            CHECK (execution_id IS NULL OR canonical_action_id IS NOT NULL);
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_canonical_case_fkey'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_canonical_case_fkey
            FOREIGN KEY (tenant_id, canonical_action_id, case_id)
            REFERENCES public.canonical_actions (tenant_id, canonical_action_id, case_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_canonical_unique'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_canonical_unique
            UNIQUE (tenant_id, canonical_action_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_execution_canonical_case_unique'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_execution_canonical_case_unique
            UNIQUE (tenant_id, execution_id, case_id, canonical_action_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.verifications'::regclass
          AND conname = 'verifications_execution_canonical_case_fkey'
    ) THEN
        ALTER TABLE public.verifications
            ADD CONSTRAINT verifications_execution_canonical_case_fkey
            FOREIGN KEY (tenant_id, execution_id, case_id, canonical_action_id)
            REFERENCES public.action_executions (tenant_id, execution_id, case_id, canonical_action_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.verifications'::regclass
          AND conname = 'verifications_identity_case_unique'
    ) THEN
        ALTER TABLE public.verifications
            ADD CONSTRAINT verifications_identity_case_unique
            UNIQUE (tenant_id, verification_id, case_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.action_executions'::regclass
          AND conname = 'action_executions_verification_identity_unique'
    ) THEN
        ALTER TABLE public.action_executions
            ADD CONSTRAINT action_executions_verification_identity_unique
            UNIQUE (
                tenant_id, execution_id, case_id, canonical_action_id,
                connector_id, resource_type, target_resource
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.verifications'::regclass
          AND conname = 'verifications_execution_resource_fkey'
    ) THEN
        ALTER TABLE public.verifications
            ADD CONSTRAINT verifications_execution_resource_fkey
            FOREIGN KEY (
                tenant_id, execution_id, case_id, canonical_action_id,
                connector_id, resource_type, target_resource
            )
            REFERENCES public.action_executions (
                tenant_id, execution_id, case_id, canonical_action_id,
                connector_id, resource_type, target_resource
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_canonical_case_fkey'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_canonical_case_fkey
            FOREIGN KEY (tenant_id, canonical_action_id, case_id)
            REFERENCES public.canonical_actions (tenant_id, canonical_action_id, case_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_execution_case_fkey'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_execution_case_fkey
            FOREIGN KEY (tenant_id, execution_id, case_id, canonical_action_id)
            REFERENCES public.action_executions (tenant_id, execution_id, case_id, canonical_action_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.escalations'::regclass
          AND conname = 'escalations_verification_case_fkey'
    ) THEN
        ALTER TABLE public.escalations
            ADD CONSTRAINT escalations_verification_case_fkey
            FOREIGN KEY (tenant_id, verification_id, case_id)
            REFERENCES public.verifications (tenant_id, verification_id, case_id);
    END IF;
END;
$$;

ALTER TABLE public.canonical_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canonical_actions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.action_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.action_executions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verifications FORCE ROW LEVEL SECURITY;
ALTER TABLE public.escalations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.escalations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS canonical_actions_tenant_isolation ON public.canonical_actions;
CREATE POLICY canonical_actions_tenant_isolation ON public.canonical_actions
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());
DROP POLICY IF EXISTS action_executions_tenant_isolation ON public.action_executions;
CREATE POLICY action_executions_tenant_isolation ON public.action_executions
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());
DROP POLICY IF EXISTS verifications_tenant_isolation ON public.verifications;
CREATE POLICY verifications_tenant_isolation ON public.verifications
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());
DROP POLICY IF EXISTS escalations_tenant_isolation ON public.escalations;
CREATE POLICY escalations_tenant_isolation ON public.escalations
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

REVOKE ALL ON TABLE public.canonical_actions, public.action_executions,
    public.verifications, public.escalations, public.cases, public.audit_records,
    public.outbox_events FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO reclaim_app';
        EXECUTE 'GRANT USAGE ON SCHEMA reclaim TO reclaim_app';
        EXECUTE 'GRANT EXECUTE ON FUNCTION reclaim.require_tenant_context() TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.canonical_actions TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.action_executions TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.verifications TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.escalations TO reclaim_app';
        EXECUTE 'GRANT SELECT, UPDATE ON TABLE public.cases TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.audit_records TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.outbox_events TO reclaim_app';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS audit_records_append_only ON public.audit_records;
CREATE TRIGGER audit_records_append_only
    BEFORE UPDATE OR DELETE ON public.audit_records
    FOR EACH ROW EXECUTE FUNCTION reclaim_reject_audit_mutation();

COMMENT ON TABLE public.action_executions IS
    'Authoritative Action Gateway lifecycle; canonical action identity is unique and UNKNOWN requires reconciliation.';
COMMENT ON TABLE public.verifications IS
    'Independent merchant-state verification linked to exactly one action execution and canonical action.';
COMMENT ON TABLE public.escalations IS
    'Tenant-owned unresolved work; owner, exposure, evidence, and lifecycle provenance are authoritative.';
