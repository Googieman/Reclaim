-- Hosted service-role and secret-delivery audit foundation.
-- Runtime credentials are provisioned separately; this migration creates only
-- NOLOGIN group roles and never contains a password or secret value.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_api') THEN
        EXECUTE 'CREATE ROLE reclaim_api NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_gateway') THEN
        EXECUTE 'CREATE ROLE reclaim_gateway NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_event_relay') THEN
        EXECUTE 'CREATE ROLE reclaim_event_relay NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_projection') THEN
        EXECUTE 'CREATE ROLE reclaim_projection NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_secret_audit') THEN
        EXECUTE 'CREATE ROLE reclaim_secret_audit NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_keycloak') THEN
        EXECUTE 'CREATE ROLE reclaim_keycloak NOLOGIN NOINHERIT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_mlflow') THEN
        EXECUTE 'CREATE ROLE reclaim_mlflow NOLOGIN NOINHERIT';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.secret_access_events (
    event_id TEXT PRIMARY KEY,
    caller_identity TEXT NOT NULL CHECK (length(btrim(caller_identity)) > 0),
    tenant_id TEXT REFERENCES public.tenants (tenant_id),
    scope TEXT NOT NULL CHECK (length(btrim(scope)) > 0),
    secret_id TEXT NOT NULL CHECK (secret_id ~ '^[a-z0-9]+([.-][a-z0-9]+)*$'),
    secret_version INTEGER CHECK (secret_version IS NULL OR secret_version >= 1),
    request_id TEXT NOT NULL CHECK (length(btrim(request_id)) > 0),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('access_intent', 'delivery', 'denied', 'rotation')),
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'released', 'rejected', 'unavailable')),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS secret_access_events_lookup_idx
    ON public.secret_access_events (caller_identity, recorded_at DESC);

REVOKE ALL ON TABLE public.secret_access_events FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO reclaim_secret_audit;
GRANT USAGE ON SCHEMA reclaim TO reclaim_secret_audit;
GRANT EXECUTE ON FUNCTION reclaim.require_tenant_context() TO reclaim_secret_audit;
GRANT INSERT ON TABLE public.secret_access_events TO reclaim_secret_audit;

ALTER TABLE public.secret_access_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.secret_access_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS secret_access_events_insert ON public.secret_access_events;
CREATE POLICY secret_access_events_insert
    ON public.secret_access_events
    FOR INSERT TO reclaim_secret_audit
    WITH CHECK (
        tenant_id IS NULL OR tenant_id = reclaim.require_tenant_context()
    );

CREATE OR REPLACE FUNCTION public.reject_secret_access_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'secret_access_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS secret_access_events_append_only ON public.secret_access_events;
CREATE TRIGGER secret_access_events_append_only
    BEFORE UPDATE OR DELETE ON public.secret_access_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_secret_access_mutation();

COMMENT ON TABLE public.secret_access_events IS
    'Append-only secret access intent and delivery metadata; plaintext values are never stored.';
