-- FS-001 tenant context, RLS, and provider webhook identity boundary.

CREATE SCHEMA IF NOT EXISTS reclaim;

CREATE OR REPLACE FUNCTION reclaim.current_tenant_id()
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('reclaim.tenant_id', true), '');
$$;

CREATE OR REPLACE FUNCTION reclaim.require_tenant_context()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    tenant TEXT := reclaim.current_tenant_id();
BEGIN
    IF tenant IS NULL THEN
        RAISE EXCEPTION 'reclaim tenant context is required';
    END IF;
    RETURN tenant;
END;
$$;

-- Provider webhook identity is intentionally not an action idempotency key.
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    connector_id TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    original_payload BYTEA NOT NULL,
    payload_checksum TEXT NOT NULL,
    raw_object_uri TEXT,
    signature TEXT,
    event_type TEXT,
    event_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    processing_status TEXT NOT NULL CHECK (
        processing_status IN ('accepted', 'duplicate', 'rejected', 'quarantined')
    ),
    incident_id TEXT,
    case_id TEXT,
    quarantine_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, connector_id, provider_event_id),
    FOREIGN KEY (tenant_id, incident_id) REFERENCES incidents (tenant_id, incident_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id)
);

-- Incomplete or unverifiable deliveries have no provider identity.  They must
-- remain auditable without inventing a provider event ID or entering the valid
-- delivery identity table.
CREATE TABLE IF NOT EXISTS webhook_quarantines (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    quarantine_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    provider_event_id TEXT,
    original_payload BYTEA NOT NULL,
    payload_checksum TEXT NOT NULL,
    raw_object_uri TEXT NOT NULL,
    signature TEXT,
    event_type TEXT,
    event_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    quarantine_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, quarantine_id)
);

ALTER TABLE webhook_deliveries
    ADD COLUMN IF NOT EXISTS raw_object_uri TEXT;

CREATE INDEX IF NOT EXISTS webhook_delivery_checksum_idx
    ON webhook_deliveries (tenant_id, payload_checksum);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'tenants', 'connector_configurations', 'incidents', 'cases',
        'evidence_items', 'timeline_events', 'attributions', 'financial_exposures',
        'policy_versions', 'action_proposals', 'policy_decisions', 'approvals',
        'action_executions', 'verifications', 'escalations', 'audit_records',
        'replay_runs', 'evaluation_cases', 'outbox_events', 'inbox_messages',
        'webhook_deliveries', 'webhook_quarantines'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'DROP POLICY IF EXISTS %I ON %I',
            table_name || '_tenant_isolation', table_name
        );
        IF table_name = 'policy_versions' THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I USING (tenant_id IS NULL OR tenant_id = reclaim.require_tenant_context()) WITH CHECK (tenant_id = reclaim.require_tenant_context())',
                table_name || '_tenant_isolation', table_name
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY %I ON %I USING (tenant_id = reclaim.require_tenant_context()) WITH CHECK (tenant_id = reclaim.require_tenant_context())',
                table_name || '_tenant_isolation', table_name
            );
        END IF;
    END LOOP;
END;
$$;

-- Keep the two identities visibly distinct in the schema.  Action idempotency
-- lives on action_proposals/action_executions; webhook identity lives above.
CREATE UNIQUE INDEX IF NOT EXISTS action_proposal_tenant_idempotency_idx
    ON action_proposals (tenant_id, idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS action_execution_tenant_idempotency_idx
    ON action_executions (tenant_id, idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS webhook_provider_identity_idx
    ON webhook_deliveries (tenant_id, connector_id, provider_event_id);
CREATE INDEX IF NOT EXISTS webhook_quarantine_identity_idx
    ON webhook_quarantines (tenant_id, connector_id, provider_event_id);
