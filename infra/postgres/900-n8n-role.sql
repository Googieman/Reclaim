-- Local-development bootstrap for n8n's isolated PostgreSQL schema/role.
-- Production deployments must provision N8N_DB_PASSWORD through the secret
-- manager. The following numbered init script applies that password.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n') THEN
        CREATE ROLE n8n LOGIN;
    END IF;
END;
$$;

GRANT CONNECT ON DATABASE reclaim TO n8n;
GRANT CREATE ON DATABASE reclaim TO n8n;
REVOKE ALL ON SCHEMA public FROM n8n;
CREATE SCHEMA IF NOT EXISTS n8n AUTHORIZATION n8n;
GRANT USAGE, CREATE ON SCHEMA n8n TO n8n;
ALTER ROLE n8n SET search_path = n8n;
