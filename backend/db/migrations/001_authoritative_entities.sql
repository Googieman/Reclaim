-- FS-001 authoritative PostgreSQL schema.
--
-- PostgreSQL owns business state.  IDs are opaque application-generated values;
-- provider identifiers are retained as data and are never used as primary keys.
-- This migration is intentionally free of provider credentials and raw secrets.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL CHECK (length(btrim(display_name)) > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connector_configurations (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    connector_id TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    connector_type TEXT NOT NULL CHECK (connector_type IN ('evidence', 'action')),
    allowed_resources JSONB NOT NULL DEFAULT '{}'::jsonb,
    allowed_operations JSONB NOT NULL DEFAULT '{}'::jsonb,
    auth_scope TEXT[] NOT NULL CHECK (cardinality(auth_scope) > 0),
    credential_scope_ref TEXT NOT NULL CHECK (length(btrim(credential_scope_ref)) > 0),
    schema_version TEXT NOT NULL,
    failure_state_version TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'simulator')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, connector_id)
);

CREATE TABLE IF NOT EXISTS incidents (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    incident_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (length(btrim(source)) > 0),
    reporter_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL,
    correlation_key TEXT NOT NULL,
    raw_input_reference TEXT,
    intake_status TEXT NOT NULL CHECK (intake_status IN ('accepted', 'rejected', 'quarantined')),
    deduplication_identity TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, incident_id),
    UNIQUE (tenant_id, deduplication_identity),
    UNIQUE (tenant_id, correlation_key)
);

CREATE TABLE IF NOT EXISTS cases (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    case_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    current_state TEXT NOT NULL CHECK (
        current_state IN (
            'intake_received', 'collecting_evidence', 'timeline_ready', 'analyzed',
            'action_pending', 'containing', 'verified_contained', 'verified_failed',
            'escalated_unresolved'
        )
    ),
    escalation_owner TEXT,
    workflow_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminal_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, case_id),
    UNIQUE (tenant_id, incident_id),
    FOREIGN KEY (tenant_id, incident_id)
        REFERENCES incidents (tenant_id, incident_id)
);

CREATE TABLE IF NOT EXISTS evidence_items (
    tenant_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    observed_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    raw_object_uri TEXT,
    checksum TEXT,
    normalization_status TEXT NOT NULL,
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'partial', 'unavailable')),
    trust_classification TEXT NOT NULL DEFAULT 'untrusted',
    collection_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, evidence_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    UNIQUE (tenant_id, connector_id, resource_type, source_identifier, checksum)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    tenant_id TEXT NOT NULL,
    timeline_event_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    canonical_event_type TEXT NOT NULL,
    source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    effective_at TIMESTAMPTZ NOT NULL,
    ordering_key TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, timeline_event_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    UNIQUE (tenant_id, case_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS attributions (
    tenant_id TEXT NOT NULL,
    attribution_id TEXT NOT NULL,
    timeline_event_id TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('malicious', 'legitimate', 'uncertain')),
    confidence NUMERIC(6, 5) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rationale TEXT NOT NULL,
    method TEXT NOT NULL,
    model_or_rules_version TEXT NOT NULL,
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, attribution_id),
    FOREIGN KEY (tenant_id, timeline_event_id)
        REFERENCES timeline_events (tenant_id, timeline_event_id)
);

CREATE TABLE IF NOT EXISTS financial_exposures (
    tenant_id TEXT NOT NULL,
    exposure_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    currency CHAR(3) NOT NULL CHECK (currency = upper(currency)),
    gross_exposure_minor BIGINT NOT NULL CHECK (gross_exposure_minor >= 0),
    recoverable_value_minor BIGINT NOT NULL CHECK (recoverable_value_minor >= 0),
    contained_value_minor BIGINT NOT NULL CHECK (contained_value_minor >= 0),
    legitimate_value_disrupted_minor BIGINT NOT NULL CHECK (legitimate_value_disrupted_minor >= 0),
    irreversible_loss_minor BIGINT NOT NULL CHECK (irreversible_loss_minor >= 0),
    remaining_exposure_minor BIGINT NOT NULL CHECK (remaining_exposure_minor >= 0),
    calculation_version TEXT NOT NULL,
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, exposure_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS policy_versions (
    policy_version_id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES tenants (tenant_id),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global', 'tenant')),
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    approval_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    author TEXT NOT NULL,
    publication_status TEXT NOT NULL CHECK (publication_status IN ('draft', 'published', 'revoked')),
    immutable_checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((scope_type = 'global' AND tenant_id IS NULL) OR (scope_type = 'tenant' AND tenant_id IS NOT NULL)),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS action_proposals (
    tenant_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_resource TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    rationale TEXT NOT NULL,
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    attribution_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_amount_minor BIGINT CHECK (requested_amount_minor IS NULL OR requested_amount_minor >= 0),
    currency CHAR(3) CHECK (currency IS NULL OR currency = upper(currency)),
    idempotency_key TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    policy_decision_id TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, proposal_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    UNIQUE (tenant_id, idempotency_key),
    CHECK (requested_amount_minor IS NULL OR currency IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    tenant_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    policy_version_id TEXT NOT NULL REFERENCES policy_versions (policy_version_id),
    result TEXT NOT NULL CHECK (result IN ('allow', 'deny', 'approval_required', 'escalate')),
    evaluated_conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluator_version TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, decision_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES action_proposals (tenant_id, proposal_id),
    UNIQUE (tenant_id, proposal_id, policy_version_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    tenant_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    approver_id TEXT NOT NULL,
    approver_role TEXT NOT NULL,
    proposer_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    policy_version_id TEXT NOT NULL REFERENCES policy_versions (policy_version_id),
    status TEXT NOT NULL CHECK (status IN ('approved', 'rejected', 'expired', 'revoked')),
    approved_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    separation_of_duties_evidence TEXT NOT NULL,
    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES action_proposals (tenant_id, proposal_id),
    CHECK (approver_id <> proposer_id),
    CHECK (expires_at IS NULL OR expires_at > approved_at)
);

CREATE TABLE IF NOT EXISTS action_executions (
    tenant_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'not_started', 'received', 'validated', 'pending_remote', 'completed', 'failed',
            'unknown', 'reconciling', 'reconciled', 'verifying', 'verified_success',
            'verified_failure', 'escalated'
        )
    ),
    remote_reference TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    result_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, execution_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES action_proposals (tenant_id, proposal_id),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS verifications (
    tenant_id TEXT NOT NULL,
    verification_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    observed_resource_state TEXT NOT NULL,
    verifier_source TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('verified_success', 'verified_failure', 'inconclusive')),
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    verified_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, verification_id),
    FOREIGN KEY (tenant_id, execution_id) REFERENCES action_executions (tenant_id, execution_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS escalations (
    tenant_id TEXT NOT NULL,
    escalation_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    reason TEXT NOT NULL,
    remaining_exposure_minor BIGINT NOT NULL CHECK (remaining_exposure_minor >= 0),
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_human_decision TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, escalation_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    CHECK ((state = 'open' AND resolved_at IS NULL) OR (state = 'resolved' AND resolved_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS audit_records (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    chain_sequence BIGINT GENERATED ALWAYS AS IDENTITY,
    audit_id TEXT NOT NULL,
    case_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    input_references TEXT[] NOT NULL DEFAULT '{}',
    output_references TEXT[] NOT NULL DEFAULT '{}',
    evidence_references TEXT[] NOT NULL DEFAULT '{}',
    policy_version_id TEXT,
    model_version TEXT,
    provider_version TEXT,
    approval_id TEXT,
    execution_id TEXT,
    correlation_ids TEXT[] NOT NULL DEFAULT '{}',
    outcome TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    previous_record_checksum TEXT,
    record_checksum TEXT NOT NULL CHECK (length(record_checksum) = 64),
    PRIMARY KEY (tenant_id, audit_id),
    UNIQUE (tenant_id, record_checksum),
    UNIQUE (chain_sequence)
);

CREATE TABLE IF NOT EXISTS replay_runs (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    run_id TEXT NOT NULL,
    fixture_version TEXT NOT NULL,
    connector_simulator_version TEXT NOT NULL,
    action_simulator_version TEXT NOT NULL,
    policy_version_id TEXT NOT NULL,
    model_provider_mode TEXT NOT NULL,
    deterministic_seed BIGINT NOT NULL CHECK (deterministic_seed >= 0),
    environment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'replay')),
    stage_outcomes JSONB NOT NULL DEFAULT '{}'::jsonb,
    terminal_state TEXT,
    differences_from_expected JSONB NOT NULL DEFAULT '[]'::jsonb,
    label TEXT NOT NULL DEFAULT 'replay',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id),
    CHECK (mode <> 'replay' OR label = 'replay')
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    evaluation_case_id TEXT NOT NULL,
    provenance JSONB NOT NULL,
    label_source TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('development', 'validation', 'held_out')),
    entity_group_id TEXT NOT NULL,
    customer_group_id TEXT,
    temporal_boundary TIMESTAMPTZ NOT NULL,
    synthetic_overlay_lineage TEXT,
    class_labels JSONB NOT NULL,
    no_compromise_false_alert BOOLEAN NOT NULL,
    mixed_legitimate_malicious BOOLEAN NOT NULL,
    expected_outcomes JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_outcomes JSONB NOT NULL DEFAULT '{}'::jsonb,
    leakage_checks JSONB NOT NULL DEFAULT '{}'::jsonb,
    held_out_access_policy TEXT NOT NULL,
    confidence_interval_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    metric_references TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, evaluation_case_id)
);

-- These tables are the durable hand-off boundary for T022/T023.  They are
-- deliberately separate from business completion and consumer offsets.
CREATE TABLE IF NOT EXISTS outbox_events (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    outbox_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    produced_at TIMESTAMPTZ NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT NOT NULL,
    producer TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    payload JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, outbox_id),
    UNIQUE (tenant_id, event_id)
);

CREATE TABLE IF NOT EXISTS inbox_messages (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    consumer_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    handled_at TIMESTAMPTZ,
    handling_status TEXT NOT NULL DEFAULT 'received'
        CHECK (handling_status IN ('received', 'handled', 'failed')),
    last_error TEXT,
    PRIMARY KEY (tenant_id, consumer_name, event_id)
);

CREATE OR REPLACE FUNCTION reclaim_reject_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_records is append-only';
END;
$$;

DROP TRIGGER IF EXISTS audit_records_append_only ON audit_records;
CREATE TRIGGER audit_records_append_only
    BEFORE UPDATE OR DELETE ON audit_records
    FOR EACH ROW EXECUTE FUNCTION reclaim_reject_audit_mutation();

CREATE INDEX IF NOT EXISTS cases_state_idx
    ON cases (tenant_id, current_state);
CREATE INDEX IF NOT EXISTS evidence_case_observed_idx
    ON evidence_items (tenant_id, case_id, observed_at);
CREATE INDEX IF NOT EXISTS timeline_case_effective_idx
    ON timeline_events (tenant_id, case_id, effective_at, ordering_key);
CREATE INDEX IF NOT EXISTS audit_tenant_recorded_idx
    ON audit_records (tenant_id, recorded_at, audit_id);
CREATE UNIQUE INDEX IF NOT EXISTS audit_tenant_predecessor_idx
    ON audit_records (tenant_id, previous_record_checksum)
    WHERE previous_record_checksum IS NOT NULL;
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx
    ON outbox_events (tenant_id, created_at)
    WHERE published_at IS NULL;
