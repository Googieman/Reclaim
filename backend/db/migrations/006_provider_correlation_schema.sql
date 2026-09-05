-- D3 corrective migration: make the provider-correlation authority explicit.
--
-- Migration 005 is already part of the migration history and may have been
-- applied with reclaim first in the migration role's search_path.  The
-- authoritative application tables are public; reclaim contains only the
-- tenant-context helper functions.  Move the legacy table when necessary and
-- make every D3 object reference explicit schema names from this point onward.

DO $$
DECLARE
    legacy_mapping_exists BOOLEAN :=
        to_regclass('reclaim.provider_correlation_mappings') IS NOT NULL;
    public_mapping_exists BOOLEAN :=
        to_regclass('public.provider_correlation_mappings') IS NOT NULL;
BEGIN
    IF legacy_mapping_exists AND public_mapping_exists THEN
        RAISE EXCEPTION
            'D3 mapping authority exists in both reclaim and public; reconcile before migration 006';
    ELSIF legacy_mapping_exists THEN
        ALTER TABLE reclaim.provider_correlation_mappings SET SCHEMA public;
    END IF;
END;
$$;

-- Migration 002 creates the reclaim helper schema before creating these two
-- tables. For a database role also named reclaim, PostgreSQL's default
-- "$user", public search path therefore placed them in reclaim. Normalize
-- that legacy/fresh-install outcome before any explicitly public D3 changes.
DO $$
DECLARE
    table_name TEXT;
    legacy_exists BOOLEAN;
    public_exists BOOLEAN;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['webhook_deliveries', 'webhook_quarantines']
    LOOP
        legacy_exists := to_regclass('reclaim.' || table_name) IS NOT NULL;
        public_exists := to_regclass('public.' || table_name) IS NOT NULL;
        IF legacy_exists AND public_exists THEN
            RAISE EXCEPTION
                'webhook table % exists in both reclaim and public; reconcile before migration 006',
                table_name;
        ELSIF legacy_exists THEN
            EXECUTE format('ALTER TABLE reclaim.%I SET SCHEMA public', table_name);
        END IF;
    END LOOP;
END;
$$;

-- The CREATE path is defensive for a partially applied 005.  A normal fresh
-- 001->005 database already has the table, either in public or in reclaim.
CREATE TABLE IF NOT EXISTS public.provider_correlation_mappings (
    tenant_id TEXT NOT NULL REFERENCES public.tenants (tenant_id),
    mapping_id TEXT NOT NULL,
    correlation_schema_version TEXT NOT NULL DEFAULT '1.0.0'
        CHECK (correlation_schema_version = '1.0.0'),
    provider TEXT NOT NULL CHECK (length(btrim(provider)) > 0),
    connector_id TEXT NOT NULL,
    provider_event_id TEXT,
    provider_payment_id TEXT,
    provider_order_id TEXT,
    merchant_reference TEXT,
    incident_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    related_order_reference TEXT,
    related_payment_reference TEXT,
    mapping_source TEXT NOT NULL CHECK (length(btrim(mapping_source)) > 0),
    mapping_source_reference TEXT NOT NULL
        CHECK (length(btrim(mapping_source_reference)) > 0),
    mapping_source_checksum TEXT NOT NULL
        CHECK (length(btrim(mapping_source_checksum)) > 0),
    mapping_status TEXT NOT NULL DEFAULT 'active'
        CHECK (mapping_status IN ('active', 'revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, mapping_id),
    UNIQUE (tenant_id, mapping_id, incident_id, case_id),
    FOREIGN KEY (tenant_id, connector_id)
        REFERENCES public.connector_configurations (tenant_id, connector_id),
    FOREIGN KEY (tenant_id, incident_id)
        REFERENCES public.incidents (tenant_id, incident_id),
    FOREIGN KEY (tenant_id, case_id, incident_id)
        REFERENCES public.cases (tenant_id, case_id, incident_id),
    CHECK (
        provider_event_id IS NOT NULL
        OR provider_payment_id IS NOT NULL
        OR provider_order_id IS NOT NULL
    ),
    CHECK (mapping_status = 'active' AND revoked_at IS NULL
           OR mapping_status = 'revoked' AND revoked_at IS NOT NULL)
);

-- A provider identity can resolve to one active owner only.  Resource mappings
-- may be reused by many event IDs; event IDs remain independently unique.
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_event_idx
    ON public.provider_correlation_mappings (provider, connector_id, provider_event_id)
    WHERE mapping_status = 'active' AND provider_event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_payment_idx
    ON public.provider_correlation_mappings (provider, connector_id, provider_payment_id)
    WHERE mapping_status = 'active' AND provider_payment_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_order_idx
    ON public.provider_correlation_mappings (provider, connector_id, provider_order_id)
    WHERE mapping_status = 'active' AND provider_order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_reference_idx
    ON public.provider_correlation_mappings (provider, connector_id, merchant_reference)
    WHERE mapping_status = 'active' AND merchant_reference IS NOT NULL;

-- Re-state the D3 delivery columns against the authoritative public tables so a
-- partial or reordered application remains deterministic.
ALTER TABLE public.webhook_deliveries
    ADD COLUMN IF NOT EXISTS authoritative_mapping_id TEXT,
    ADD COLUMN IF NOT EXISTS related_order_reference TEXT,
    ADD COLUMN IF NOT EXISTS related_payment_reference TEXT,
    ADD COLUMN IF NOT EXISTS verified_correlation JSONB,
    ADD COLUMN IF NOT EXISTS asserted_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_merchant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_incident_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_case_id TEXT,
    ADD COLUMN IF NOT EXISTS assertion_status TEXT;

ALTER TABLE public.webhook_quarantines
    ADD COLUMN IF NOT EXISTS verified_correlation JSONB,
    ADD COLUMN IF NOT EXISTS association_status TEXT,
    ADD COLUMN IF NOT EXISTS asserted_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_merchant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_incident_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_case_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'webhook_delivery_mapping_fkey'
          AND conrelid = 'public.webhook_deliveries'::regclass
    ) THEN
        ALTER TABLE public.webhook_deliveries
            ADD CONSTRAINT webhook_delivery_mapping_fkey
            FOREIGN KEY (tenant_id, authoritative_mapping_id, incident_id, case_id)
            REFERENCES public.provider_correlation_mappings (
                tenant_id, mapping_id, incident_id, case_id
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'webhook_delivery_verified_correlation_object'
          AND conrelid = 'public.webhook_deliveries'::regclass
    ) THEN
        ALTER TABLE public.webhook_deliveries
            ADD CONSTRAINT webhook_delivery_verified_correlation_object
            CHECK (
                verified_correlation IS NULL
                OR jsonb_typeof(verified_correlation) = 'object'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'webhook_delivery_authority_check'
          AND conrelid = 'public.webhook_deliveries'::regclass
    ) THEN
        ALTER TABLE public.webhook_deliveries
            ADD CONSTRAINT webhook_delivery_authority_check
            CHECK (
                processing_status NOT IN ('accepted', 'duplicate')
                OR (
                    authoritative_mapping_id IS NOT NULL
                    AND incident_id IS NOT NULL
                    AND case_id IS NOT NULL
                    AND verified_correlation IS NOT NULL
                    AND assertion_status IN ('not_supplied', 'matched')
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'webhook_quarantine_correlation_object'
          AND conrelid = 'public.webhook_quarantines'::regclass
    ) THEN
        ALTER TABLE public.webhook_quarantines
            ADD CONSTRAINT webhook_quarantine_correlation_object
            CHECK (
                verified_correlation IS NULL
                OR jsonb_typeof(verified_correlation) = 'object'
            );
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS webhook_delivery_mapping_idx
    ON public.webhook_deliveries (tenant_id, authoritative_mapping_id);
CREATE INDEX IF NOT EXISTS webhook_quarantine_association_idx
    ON public.webhook_quarantines (tenant_id, association_status);

ALTER TABLE public.webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_deliveries FORCE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_quarantines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_quarantines FORCE ROW LEVEL SECURITY;

ALTER TABLE public.provider_correlation_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_correlation_mappings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS provider_correlation_mappings_tenant_isolation
    ON public.provider_correlation_mappings;
CREATE POLICY provider_correlation_mappings_tenant_isolation
    ON public.provider_correlation_mappings
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());

-- Mapping authority is provisioned by the trusted service boundary and revoked
-- by update; it is never deleted by the application role.  The conditional
-- grant keeps this migration usable when role provisioning is external.
REVOKE ALL ON TABLE public.provider_correlation_mappings FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO reclaim_app';
        EXECUTE 'GRANT USAGE ON SCHEMA reclaim TO reclaim_app';
        EXECUTE 'GRANT EXECUTE ON FUNCTION reclaim.require_tenant_context() TO reclaim_app';
        EXECUTE 'REVOKE ALL ON TABLE public.provider_correlation_mappings FROM reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.provider_correlation_mappings TO reclaim_app';
    END IF;
END;
$$;
