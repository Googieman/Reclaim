-- US2 MAJOR-2 remediation: separate canonical action identity from the
-- analysis-specific proposal occurrence.
--
-- model_run_proposals remains one row per analysis/proposal occurrence.  The
-- canonical_actions table is the PostgreSQL authority for the semantic action
-- identity, so multiple analyses can retain provenance while sharing exactly
-- one canonical action row.

CREATE TABLE IF NOT EXISTS public.canonical_actions (
    tenant_id TEXT NOT NULL REFERENCES public.tenants (tenant_id),
    canonical_action_id TEXT NOT NULL
        CHECK (canonical_action_id ~ '^[0-9a-f]{64}$'),
    case_id TEXT NOT NULL,
    identity_version TEXT NOT NULL DEFAULT 'action-identity-v1.0.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, canonical_action_id),
    UNIQUE (tenant_id, canonical_action_id, case_id),
    FOREIGN KEY (tenant_id, case_id)
        REFERENCES public.cases (tenant_id, case_id),
    CHECK (identity_version = 'action-identity-v1.0.0')
);

-- Migration 007-009 did not retain enough authoritative resource data to
-- recompute the corrected identity without risk.  Refuse an upgrade with
-- historical action identities rather than silently inventing or reusing an
-- analysis-scoped value.  A successful application is idempotent: on later
-- runs the column exists and only the invariant checks below are repeated.
DO $$
DECLARE
    canonical_column_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'model_run_proposals'
          AND column_name = 'canonical_action_id'
    ) INTO canonical_column_exists;

    IF NOT canonical_column_exists THEN
        IF EXISTS (SELECT 1 FROM public.model_run_proposals) THEN
            RAISE EXCEPTION
                'migration 010 cannot safely backfill historical model_run_proposals canonical identities';
        END IF;
        ALTER TABLE public.model_run_proposals
            ADD COLUMN canonical_action_id TEXT;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.model_run_proposals
        WHERE (
            validation_status = 'valid'
            AND canonical_action_id IS NULL
        ) OR (
            canonical_action_id IS NULL
            AND validation ->> 'canonical_action_identity' IS NOT NULL
        )
    ) THEN
        RAISE EXCEPTION
            'migration 010 found model_run_proposals requiring unsafe canonical identity backfill';
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.model_run_proposals'::regclass
          AND conname = 'model_run_proposals_canonical_action_check'
    ) THEN
        ALTER TABLE public.model_run_proposals
            ADD CONSTRAINT model_run_proposals_canonical_action_check
            CHECK (validation_status <> 'valid' OR canonical_action_id IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.model_run_proposals'::regclass
          AND conname = 'model_run_proposals_canonical_action_fkey'
    ) THEN
        ALTER TABLE public.model_run_proposals
            ADD CONSTRAINT model_run_proposals_canonical_action_fkey
            FOREIGN KEY (tenant_id, canonical_action_id, case_id)
            REFERENCES public.canonical_actions (
                tenant_id, canonical_action_id, case_id
            );
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS model_run_proposals_canonical_action_idx
    ON public.model_run_proposals (tenant_id, canonical_action_id);

ALTER TABLE public.canonical_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canonical_actions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS canonical_actions_tenant_isolation
    ON public.canonical_actions;
CREATE POLICY canonical_actions_tenant_isolation
    ON public.canonical_actions
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

ALTER TABLE public.model_run_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_run_proposals FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.canonical_actions FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO reclaim_app';
        EXECUTE 'GRANT USAGE ON SCHEMA reclaim TO reclaim_app';
        EXECUTE 'GRANT EXECUTE ON FUNCTION reclaim.require_tenant_context() TO reclaim_app';
        EXECUTE 'REVOKE ALL ON TABLE public.canonical_actions FROM reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.canonical_actions TO reclaim_app';
    END IF;
END;
$$;

COMMENT ON TABLE public.canonical_actions IS
    'One authoritative semantic action identity; analysis proposal occurrences retain provenance separately.';
COMMENT ON COLUMN public.canonical_actions.canonical_action_id IS
    'SHA-256 of the versioned authoritative semantic action representation.';
COMMENT ON COLUMN public.model_run_proposals.canonical_action_id IS
    'Authoritative semantic action identity shared across analysis proposal occurrences.';
