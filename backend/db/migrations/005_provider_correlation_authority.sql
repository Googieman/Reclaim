-- D3 / MAJOR-5: verified provider correlation and authoritative association.
-- PostgreSQL remains the only source of provider-to-incident/case authority.

-- Composite case identity is required before a mapping can prove that its
-- incident and case belong to one another, not merely to the same tenant.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'cases_tenant_case_incident_key'
    ) THEN
        ALTER TABLE cases
            ADD CONSTRAINT cases_tenant_case_incident_key
            UNIQUE (tenant_id, case_id, incident_id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS provider_correlation_mappings (
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
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
        REFERENCES connector_configurations (tenant_id, connector_id),
    FOREIGN KEY (tenant_id, incident_id)
        REFERENCES incidents (tenant_id, incident_id),
    FOREIGN KEY (tenant_id, case_id, incident_id)
        REFERENCES cases (tenant_id, case_id, incident_id),
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
    ON provider_correlation_mappings (provider, connector_id, provider_event_id)
    WHERE mapping_status = 'active' AND provider_event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_payment_idx
    ON provider_correlation_mappings (provider, connector_id, provider_payment_id)
    WHERE mapping_status = 'active' AND provider_payment_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_order_idx
    ON provider_correlation_mappings (provider, connector_id, provider_order_id)
    WHERE mapping_status = 'active' AND provider_order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS provider_mapping_active_reference_idx
    ON provider_correlation_mappings (provider, connector_id, merchant_reference)
    WHERE mapping_status = 'active' AND merchant_reference IS NOT NULL;

ALTER TABLE webhook_deliveries
    ADD COLUMN IF NOT EXISTS authoritative_mapping_id TEXT,
    ADD COLUMN IF NOT EXISTS related_order_reference TEXT,
    ADD COLUMN IF NOT EXISTS related_payment_reference TEXT,
    ADD COLUMN IF NOT EXISTS verified_correlation JSONB,
    ADD COLUMN IF NOT EXISTS asserted_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_merchant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_incident_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_case_id TEXT,
    ADD COLUMN IF NOT EXISTS assertion_status TEXT;

ALTER TABLE webhook_quarantines
    ADD COLUMN IF NOT EXISTS verified_correlation JSONB,
    ADD COLUMN IF NOT EXISTS association_status TEXT,
    ADD COLUMN IF NOT EXISTS asserted_tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_merchant_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_incident_id TEXT,
    ADD COLUMN IF NOT EXISTS asserted_case_id TEXT;

-- Existing development deliveries have no proof under the new contract.  Move
-- them to quarantine without using their caller-selected case or incident IDs.
-- This is deliberately idempotent: a second migration sees no legacy accepted
-- row that lacks verified authority.
-- Migration execution is a controlled schema-change window.  Existing webhook
-- tables already have FORCE RLS from migration 002, but the legacy rows span
-- tenants and cannot be copied with one transaction-local tenant setting.
ALTER TABLE webhook_deliveries DISABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_quarantines DISABLE ROW LEVEL SECURITY;

INSERT INTO webhook_quarantines (
    tenant_id, quarantine_id, connector_id, provider_event_id, original_payload,
    payload_checksum, raw_object_uri, signature, event_type, event_timestamp,
    received_at, quarantine_reason, association_status, asserted_tenant_id,
    asserted_incident_id, asserted_case_id
)
SELECT
    delivery.tenant_id,
    'legacy-unresolved:' || delivery.connector_id || ':' || delivery.provider_event_id,
    delivery.connector_id,
    delivery.provider_event_id,
    delivery.original_payload,
    delivery.payload_checksum,
    COALESCE(
        delivery.raw_object_uri,
        'legacy://unresolved/' || delivery.tenant_id || '/' || delivery.provider_event_id
    ),
    delivery.signature,
    delivery.event_type,
    delivery.event_timestamp,
    delivery.received_at,
    'unresolved_association: legacy delivery has no verified provider mapping',
    'unresolved_association',
    delivery.tenant_id,
    delivery.incident_id,
    delivery.case_id
FROM webhook_deliveries AS delivery
WHERE delivery.processing_status IN ('accepted', 'duplicate')
  AND (
      delivery.authoritative_mapping_id IS NULL
      OR delivery.verified_correlation IS NULL
      OR delivery.incident_id IS NULL
      OR delivery.case_id IS NULL
      OR NOT EXISTS (
          SELECT 1
          FROM provider_correlation_mappings AS mapping
          WHERE mapping.tenant_id = delivery.tenant_id
            AND mapping.mapping_id = delivery.authoritative_mapping_id
            AND mapping.incident_id = delivery.incident_id
            AND mapping.case_id = delivery.case_id
            AND mapping.mapping_status = 'active'
      )
  )
ON CONFLICT (tenant_id, quarantine_id) DO NOTHING;

DELETE FROM webhook_deliveries AS delivery
WHERE delivery.processing_status IN ('accepted', 'duplicate')
  AND (
      delivery.authoritative_mapping_id IS NULL
      OR delivery.verified_correlation IS NULL
      OR delivery.incident_id IS NULL
      OR delivery.case_id IS NULL
      OR NOT EXISTS (
          SELECT 1
          FROM provider_correlation_mappings AS mapping
          WHERE mapping.tenant_id = delivery.tenant_id
            AND mapping.mapping_id = delivery.authoritative_mapping_id
            AND mapping.incident_id = delivery.incident_id
            AND mapping.case_id = delivery.case_id
            AND mapping.mapping_status = 'active'
      )
  );

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY;
ALTER TABLE webhook_quarantines ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_quarantines FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'webhook_delivery_mapping_fkey'
    ) THEN
        ALTER TABLE webhook_deliveries
            ADD CONSTRAINT webhook_delivery_mapping_fkey
            FOREIGN KEY (tenant_id, authoritative_mapping_id, incident_id, case_id)
            REFERENCES provider_correlation_mappings (
                tenant_id, mapping_id, incident_id, case_id
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'webhook_delivery_verified_correlation_object'
    ) THEN
        ALTER TABLE webhook_deliveries
            ADD CONSTRAINT webhook_delivery_verified_correlation_object
            CHECK (
                verified_correlation IS NULL
                OR jsonb_typeof(verified_correlation) = 'object'
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'webhook_delivery_authority_check'
    ) THEN
        ALTER TABLE webhook_deliveries
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
        SELECT 1 FROM pg_constraint
        WHERE conname = 'webhook_quarantine_correlation_object'
    ) THEN
        ALTER TABLE webhook_quarantines
            ADD CONSTRAINT webhook_quarantine_correlation_object
            CHECK (
                verified_correlation IS NULL
                OR jsonb_typeof(verified_correlation) = 'object'
            );
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS webhook_delivery_mapping_idx
    ON webhook_deliveries (tenant_id, authoritative_mapping_id);
CREATE INDEX IF NOT EXISTS webhook_quarantine_association_idx
    ON webhook_quarantines (tenant_id, association_status);

ALTER TABLE provider_correlation_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_correlation_mappings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS provider_correlation_mappings_tenant_isolation
    ON provider_correlation_mappings;
CREATE POLICY provider_correlation_mappings_tenant_isolation
    ON provider_correlation_mappings
    USING (tenant_id = reclaim.require_tenant_context())
    WITH CHECK (tenant_id = reclaim.require_tenant_context());
