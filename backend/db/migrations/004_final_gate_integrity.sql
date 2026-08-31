-- Final US1 remediation: serialize audit chains and retain timeline uncertainty.

-- Existing deployments receive the same columns declared in migration 001.
ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS timeline_uncertainty JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE timeline_events
    ADD COLUMN IF NOT EXISTS conflicting_source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE timeline_events
    ADD COLUMN IF NOT EXISTS uncertainty_reasons JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'cases_timeline_uncertainty_array'
    ) THEN
        ALTER TABLE cases
            ADD CONSTRAINT cases_timeline_uncertainty_array
            CHECK (jsonb_typeof(timeline_uncertainty) = 'array');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'timeline_conflicting_source_event_ids_array'
    ) THEN
        ALTER TABLE timeline_events
            ADD CONSTRAINT timeline_conflicting_source_event_ids_array
            CHECK (jsonb_typeof(conflicting_source_event_ids) = 'array');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'timeline_uncertainty_reasons_array'
    ) THEN
        ALTER TABLE timeline_events
            ADD CONSTRAINT timeline_uncertainty_reasons_array
            CHECK (jsonb_typeof(uncertainty_reasons) = 'array');
    END IF;
END;
$$;

-- Defense in depth for callers that bypass the AuditChain service.
CREATE UNIQUE INDEX IF NOT EXISTS audit_tenant_root_idx
    ON audit_records (tenant_id)
    WHERE previous_record_checksum IS NULL;
