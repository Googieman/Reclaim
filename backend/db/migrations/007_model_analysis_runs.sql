-- US2 T076: authoritative persistence for parsed model analysis and validated
-- proposal provenance.  These rows are advisory history only; they do not grant
-- policy approval or an Action Gateway execution capability.

CREATE TABLE IF NOT EXISTS public.model_runs (
    tenant_id TEXT NOT NULL REFERENCES public.tenants (tenant_id),
    analysis_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    deterministic_seed TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'replay', 'deterministic_only')),
    replay_label TEXT NOT NULL CHECK (replay_label IN ('live', 'replay', 'deterministic_only')),
    provider TEXT,
    model TEXT,
    adapter_version TEXT,
    request_schema_version TEXT NOT NULL,
    response_schema_version TEXT,
    parser_version TEXT,
    request_checksum TEXT NOT NULL CHECK (request_checksum ~ '^[0-9a-f]{64}$'),
    response_checksum TEXT CHECK (response_checksum IS NULL OR response_checksum ~ '^[0-9a-f]{64}$'),
    deterministic_analysis_checksum TEXT NOT NULL
        CHECK (deterministic_analysis_checksum ~ '^[0-9a-f]{64}$'),
    deterministic_exposure_checksum TEXT NOT NULL
        CHECK (deterministic_exposure_checksum ~ '^[0-9a-f]{64}$'),
    input_references TEXT[] NOT NULL DEFAULT '{}',
    output_references TEXT[] NOT NULL DEFAULT '{}',
    evidence_references TEXT[] NOT NULL DEFAULT '{}',
    timeline_references TEXT[] NOT NULL DEFAULT '{}',
    attribution_versions TEXT[] NOT NULL DEFAULT '{}',
    feature_schema_version TEXT,
    exposure_version TEXT NOT NULL,
    exposure_currency CHAR(3) NOT NULL CHECK (exposure_currency = upper(exposure_currency)),
    gross_exposure_minor BIGINT NOT NULL CHECK (gross_exposure_minor >= 0),
    recoverable_value_minor BIGINT NOT NULL CHECK (recoverable_value_minor >= 0),
    contained_value_minor BIGINT NOT NULL CHECK (contained_value_minor >= 0),
    legitimate_value_disrupted_minor BIGINT NOT NULL CHECK (legitimate_value_disrupted_minor >= 0),
    irreversible_loss_minor BIGINT NOT NULL CHECK (irreversible_loss_minor >= 0),
    remaining_exposure_minor BIGINT NOT NULL CHECK (remaining_exposure_minor >= 0),
    uncertainty JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(uncertainty) = 'array'),
    refusal_records JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(refusal_records) = 'array'),
    forbidden_attempts JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(forbidden_attempts) = 'array'),
    provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    requested_mode TEXT NOT NULL DEFAULT 'replay'
        CHECK (requested_mode IN ('live', 'replay')),
    terminal_outcome TEXT NOT NULL DEFAULT 'completed'
        CHECK (terminal_outcome IN ('completed', 'deterministic_only', 'escalation', 'refusal')),
    fallback_reason TEXT,
    PRIMARY KEY (tenant_id, analysis_id),
    UNIQUE (tenant_id, analysis_id, case_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES public.cases (tenant_id, case_id),
    CHECK (mode = replay_label),
    CHECK (
        (mode = 'deterministic_only'
            AND provider IS NULL AND model IS NULL AND adapter_version IS NULL
            AND response_schema_version IS NULL AND parser_version IS NULL
            AND response_checksum IS NULL)
        OR
        (mode IN ('live', 'replay')
            AND provider IS NOT NULL AND model IS NOT NULL AND adapter_version IS NOT NULL
            AND response_schema_version IS NOT NULL AND parser_version IS NOT NULL
            AND response_checksum IS NOT NULL)
    ),
    CHECK (recoverable_value_minor <= gross_exposure_minor),
    CHECK (contained_value_minor <= recoverable_value_minor),
    CHECK (irreversible_loss_minor = gross_exposure_minor - recoverable_value_minor),
    CHECK (remaining_exposure_minor = recoverable_value_minor - contained_value_minor)
);

CREATE TABLE IF NOT EXISTS public.model_run_proposals (
    tenant_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    proposal_checksum TEXT NOT NULL CHECK (proposal_checksum ~ '^[0-9a-f]{64}$'),
    validation_status TEXT NOT NULL
        CHECK (validation_status IN ('valid', 'rejected', 'escalation_only')),
    validation_version TEXT NOT NULL,
    validation_checksum TEXT NOT NULL CHECK (validation_checksum ~ '^[0-9a-f]{64}$'),
    authoritative_input_checksum TEXT NOT NULL
        CHECK (authoritative_input_checksum ~ '^[0-9a-f]{64}$'),
    policy_evaluation_ready BOOLEAN NOT NULL,
    execution_state TEXT NOT NULL DEFAULT 'not_executable'
        CHECK (execution_state = 'not_executable'),
    approval_state TEXT NOT NULL DEFAULT 'not_approved'
        CHECK (approval_state = 'not_approved'),
    proposal JSONB NOT NULL CHECK (jsonb_typeof(proposal) = 'object'),
    validation JSONB NOT NULL CHECK (jsonb_typeof(validation) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, analysis_id, proposal_id),
    FOREIGN KEY (tenant_id, analysis_id, case_id)
        REFERENCES public.model_runs (tenant_id, analysis_id, case_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES public.cases (tenant_id, case_id),
    CHECK (policy_evaluation_ready = (validation_status = 'valid'))
);

ALTER TABLE public.model_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS model_runs_tenant_isolation ON public.model_runs;
CREATE POLICY model_runs_tenant_isolation ON public.model_runs
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

ALTER TABLE public.model_run_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_run_proposals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS model_run_proposals_tenant_isolation ON public.model_run_proposals;
CREATE POLICY model_run_proposals_tenant_isolation ON public.model_run_proposals
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

CREATE INDEX IF NOT EXISTS model_runs_case_created_idx
    ON public.model_runs (tenant_id, case_id, created_at, analysis_id);
CREATE INDEX IF NOT EXISTS model_run_proposals_analysis_idx
    ON public.model_run_proposals (tenant_id, analysis_id, proposal_id);
