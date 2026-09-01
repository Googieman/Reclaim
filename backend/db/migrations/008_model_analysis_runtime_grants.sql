-- US2 corrective migration: grant the runtime role only the model-analysis
-- persistence permissions used by ModelRunRepository.
--
-- Migration 007 created the tables and forced tenant RLS but did not grant the
-- non-owner runtime role access.  ModelRunRepository only reads and inserts
-- model-run and model-run-proposal rows; policy, approval, execution, and
-- deletion remain outside this advisory persistence boundary.

REVOKE ALL ON TABLE public.model_runs, public.model_run_proposals FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app') THEN
        -- Keep the same explicit runtime-role convention as migration 006.
        EXECUTE 'GRANT USAGE ON SCHEMA public TO reclaim_app';
        EXECUTE 'GRANT USAGE ON SCHEMA reclaim TO reclaim_app';
        EXECUTE 'GRANT EXECUTE ON FUNCTION reclaim.require_tenant_context() TO reclaim_app';
        EXECUTE 'REVOKE ALL ON TABLE public.model_runs, public.model_run_proposals FROM reclaim_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE public.model_runs, public.model_run_proposals TO reclaim_app';
    END IF;
END;
$$;
