-- US3 T090: approval lifecycle optimistic concurrency.
--
-- Approval records remain tenant-scoped and mutable only through explicit
-- lifecycle transitions.  The version makes a stale approve/reject/expire/
-- revoke command fail closed instead of silently overwriting a newer decision.

ALTER TABLE public.approvals
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public.approvals
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE public.approvals
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT 'legacy-approval';

UPDATE public.approvals
SET correlation_id = 'legacy-approval'
WHERE correlation_id IS NULL OR length(btrim(correlation_id)) = 0;
ALTER TABLE public.approvals
    ALTER COLUMN correlation_id SET DEFAULT 'legacy-approval',
    ALTER COLUMN correlation_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.approvals'::regclass
          AND conname = 'approvals_correlation_id_nonblank'
    ) THEN
        ALTER TABLE public.approvals
            ADD CONSTRAINT approvals_correlation_id_nonblank
            CHECK (length(btrim(correlation_id)) > 0);
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.approvals'::regclass
          AND conname = 'approvals_version_nonnegative'
    ) THEN
        ALTER TABLE public.approvals
            ADD CONSTRAINT approvals_version_nonnegative CHECK (version >= 0);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS approvals_tenant_proposal_idx
    ON public.approvals (tenant_id, proposal_id, case_id, version);
