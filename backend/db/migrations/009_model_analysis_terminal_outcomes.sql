-- US2 MAJOR-4 remediation: make the authoritative model-run row represent a
-- response-less deterministic terminal outcome without fabricating provider data.
--
-- Existing model runs retain their accepted response metadata.  New
-- deterministic-only/escalation/refusal rows use deterministic_only mode and
-- NULL provider/response columns, while requested mode and terminal outcome
-- remain explicit and tenant-bound.

ALTER TABLE public.model_runs
    ADD COLUMN IF NOT EXISTS requested_mode TEXT,
    ADD COLUMN IF NOT EXISTS terminal_outcome TEXT,
    ADD COLUMN IF NOT EXISTS fallback_reason TEXT;

ALTER TABLE public.model_runs
    ALTER COLUMN provider DROP NOT NULL,
    ALTER COLUMN model DROP NOT NULL,
    ALTER COLUMN adapter_version DROP NOT NULL,
    ALTER COLUMN response_schema_version DROP NOT NULL,
    ALTER COLUMN parser_version DROP NOT NULL,
    ALTER COLUMN response_checksum DROP NOT NULL;

UPDATE public.model_runs
SET requested_mode = mode
WHERE requested_mode IS NULL
  AND mode IN ('live', 'replay');

UPDATE public.model_runs
SET terminal_outcome = 'completed'
WHERE terminal_outcome IS NULL;

ALTER TABLE public.model_runs
    ALTER COLUMN requested_mode SET DEFAULT 'replay',
    ALTER COLUMN requested_mode SET NOT NULL,
    ALTER COLUMN terminal_outcome SET DEFAULT 'completed',
    ALTER COLUMN terminal_outcome SET NOT NULL;

DO $$
DECLARE
    constraint_record RECORD;
BEGIN
    -- Migration 007 used unnamed checks.  Drop only the old mode/response
    -- checks so the financial arithmetic and tenant/case constraints remain
    -- intact.
    FOR constraint_record IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'public.model_runs'::regclass
          AND contype = 'c'
          AND (
              pg_get_constraintdef(oid) ILIKE '%mode%'
              OR pg_get_constraintdef(oid) ILIKE '%replay_label%'
              OR pg_get_constraintdef(oid) ILIKE '%response_checksum%'
              OR pg_get_constraintdef(oid) ILIKE '%terminal_outcome%'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE public.model_runs DROP CONSTRAINT %I',
            constraint_record.conname
        );
    END LOOP;
END;
$$;

ALTER TABLE public.model_runs
    ADD CONSTRAINT model_runs_mode_final_check
        CHECK (mode IN ('live', 'replay', 'deterministic_only')),
    ADD CONSTRAINT model_runs_replay_label_final_check
        CHECK (replay_label IN ('live', 'replay', 'deterministic_only')),
    ADD CONSTRAINT model_runs_requested_mode_check
        CHECK (requested_mode IN ('live', 'replay')),
    ADD CONSTRAINT model_runs_terminal_outcome_check
        CHECK (terminal_outcome IN ('completed', 'deterministic_only', 'escalation', 'refusal')),
    ADD CONSTRAINT model_runs_mode_replay_label_final_check
        CHECK (mode = replay_label),
    ADD CONSTRAINT model_runs_response_metadata_check
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
        );

COMMENT ON COLUMN public.model_runs.requested_mode IS
    'Mode requested before any provider fallback; distinct from final mode.';
COMMENT ON COLUMN public.model_runs.terminal_outcome IS
    'Final analysis outcome, separate from live/replay source mode.';
COMMENT ON COLUMN public.model_runs.fallback_reason IS
    'Bounded, sanitized reason for a response-less terminal outcome.';
