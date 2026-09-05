-- Incident Intake / Case Inbox / n8n migration.
-- PostgreSQL remains authoritative; the n8n database stores only workflow
-- execution metadata in its isolated schema.

ALTER TABLE public.incidents
    ADD COLUMN IF NOT EXISTS incident_type TEXT,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS narrative_checksum TEXT,
    ADD COLUMN IF NOT EXISTS customer_reference TEXT,
    ADD COLUMN IF NOT EXISTS account_reference TEXT,
    ADD COLUMN IF NOT EXISTS order_reference TEXT,
    ADD COLUMN IF NOT EXISTS payment_reference TEXT,
    ADD COLUMN IF NOT EXISTS reported_amount_minor BIGINT,
    ADD COLUMN IF NOT EXISTS reported_currency CHAR(3),
    ADD COLUMN IF NOT EXISTS external_reference TEXT;

ALTER TABLE public.incidents
    DROP CONSTRAINT IF EXISTS incidents_reported_amount_currency_check;
ALTER TABLE public.incidents
    ADD CONSTRAINT incidents_reported_amount_currency_check
    CHECK (
        (reported_amount_minor IS NULL AND reported_currency IS NULL)
        OR (reported_amount_minor IS NOT NULL AND reported_amount_minor >= 0
            AND reported_currency IS NOT NULL AND reported_currency = upper(reported_currency))
    );

ALTER TABLE public.incidents
    DROP CONSTRAINT IF EXISTS incidents_incident_type_check;
ALTER TABLE public.incidents
    ADD CONSTRAINT incidents_incident_type_check
    CHECK (
        incident_type IS NULL OR incident_type IN (
            'account_takeover', 'unauthorized_payment', 'refund_abuse',
            'chargeback', 'policy_abuse', 'other'
        )
    );

CREATE INDEX IF NOT EXISTS incidents_identifier_search_idx
    ON public.incidents (
        tenant_id, lower(coalesce(customer_reference, '')),
        lower(coalesce(account_reference, '')),
        lower(coalesce(order_reference, '')),
        lower(coalesce(payment_reference, '')),
        lower(coalesce(external_reference, ''))
    );

CREATE TABLE IF NOT EXISTS public.orchestration_runs (
    tenant_id TEXT NOT NULL REFERENCES public.tenants (tenant_id),
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    external_execution_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('normalize_intake', 'analyze', 'human_handoff')),
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'awaiting_human', 'completed', 'failed', 'requires_attention')
    ),
    idempotency_key TEXT NOT NULL,
    failure_code TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES public.cases (tenant_id, case_id),
    UNIQUE (tenant_id, case_id, idempotency_key),
    UNIQUE (tenant_id, external_execution_id),
    CHECK (status NOT IN ('failed', 'requires_attention') OR failure_code IS NOT NULL),
    CHECK (completed_at IS NULL OR completed_at >= queued_at)
);

CREATE INDEX IF NOT EXISTS orchestration_runs_case_latest_idx
    ON public.orchestration_runs (tenant_id, case_id, updated_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS orchestration_runs_status_idx
    ON public.orchestration_runs (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.orchestration_stage_attempts (
    tenant_id TEXT NOT NULL REFERENCES public.tenants (tenant_id),
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('normalize_intake', 'analyze', 'human_handoff')),
    idempotency_key TEXT NOT NULL,
    expected_state TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'awaiting_human', 'failed', 'requires_attention')),
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, attempt_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES public.orchestration_runs (tenant_id, run_id),
    UNIQUE (tenant_id, run_id, stage, idempotency_key),
    CHECK (outcome NOT IN ('failed', 'requires_attention') OR failure_code IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS orchestration_stage_attempts_run_idx
    ON public.orchestration_stage_attempts (tenant_id, run_id, created_at);

ALTER TABLE public.orchestration_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orchestration_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS orchestration_runs_tenant_isolation ON public.orchestration_runs;
CREATE POLICY orchestration_runs_tenant_isolation
    ON public.orchestration_runs
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

ALTER TABLE public.orchestration_stage_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orchestration_stage_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS orchestration_stage_attempts_tenant_isolation
    ON public.orchestration_stage_attempts;
CREATE POLICY orchestration_stage_attempts_tenant_isolation
    ON public.orchestration_stage_attempts
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

REVOKE ALL ON TABLE public.orchestration_runs FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.orchestration_runs TO reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.orchestration_stage_attempts TO reclaim_app';
    END IF;
END;
$$;

COMMENT ON TABLE public.orchestration_runs IS
    'Authoritative RECLAIM handoff state; n8n execution history is operational metadata only.';
COMMENT ON COLUMN public.incidents.narrative_checksum IS
    'Checksum of narrative retained in immutable MinIO; narrative is never emitted in domain events.';
