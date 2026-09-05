# Migration rehearsal and rollback guidance

Run this rehearsal against a disposable project and isolated PostgreSQL/MinIO
targets. The authoritative production database, preserved T153 project, and
production evidence bucket are never reset by a rehearsal.

## Before migration

1. Capture a PostgreSQL custom-format backup and MinIO immutable snapshot using the
   backup scripts. Verify both SHA-256 manifests and record artifact timestamps.
2. Record the current migration version, n8n workflow version, n8n execution
   inventory, and the Temporal legacy-run inventory. New work remains n8n-owned;
   Temporal is drain-only and is not removed by this rehearsal.
3. Confirm live actions and live financial actions are disabled and that no backup
   manifest contains credentials, raw narratives, or private evidence.

## Rehearse forward migration

Restore PostgreSQL into `reclaim_restore_<run_id>` and MinIO into a new empty,
versioned/object-locked bucket. Run the checked-in migrations in order and verify:

- PostgreSQL schema and migration markers are complete and idempotent.
- Tenant RLS is forced and the n8n schema/role has only its declared scoped access.
- Outbox/inbox records, orchestration stage attempts, and audit chain checksums are
  readable from PostgreSQL.
- MinIO object checksums match the manifest and raw content is not emitted to logs.
- API readiness, n8n worker recovery, redpanda handoff, and read-only replay smoke
  pass without any merchant connector or financial side effect.

Record actual elapsed migration and recovery times. Compare them with RPO 15
minutes and RTO 60 minutes, but do not call the objectives met without measured
timestamps.

## Rollback decision

Rollback is required when a migration fails, a checksum differs, RLS or n8n
ownership changes unexpectedly, an audit chain cannot be verified, or readiness
does not recover within the declared RTO. First stop new intake and preserve logs
and correlation-linked audit evidence. Do not retry an uncertain non-idempotent
operation.

Rollback is an isolated restore to the last verified PostgreSQL dump and MinIO
snapshot, followed by the same schema, checksum, RLS, readiness, and replay
checks. The `restore-postgres.ps1` helper uses `pg_restore` with a single
transaction and refuses to overwrite an existing target. The MinIO helper refuses
an existing bucket. This is the rollback path; there is no destructive in-place
reset command in this repository.

After rollback, compare the n8n execution inventory with PostgreSQL orchestration
state. Resume only from an authoritative stage attempt, and preserve Temporal
drain state. If inventory and PostgreSQL disagree, quarantine the run and escalate
rather than replaying delivery blindly.

## Exit evidence

The operator records the environment/project, artifact IDs and SHA-256 values,
migration range, schema/RLS checks, object count/checksum result, n8n/Temporal
inventories, observed RPO/RTO, service recovery outcomes, and remaining blockers.
Static readiness and live qualification are reported separately. No production
readiness, financial correctness, or connector qualification is inferred from a
successful local rehearsal.

## T154 Temporal drain/removal gate

Temporal remains present as a legacy drain path until every item below has an
explicit deployment-owned record. This is a fail-closed checklist: an empty
result, missing record, or disagreement is a blocker. Operators: do not remove
the Temporal SDK or service while any item is unresolved.

- Empty run inventory: query the authoritative Temporal legacy-run inventory and
  record the query timestamp, result, and operator/change identifier.
- Parity: compare every remaining Temporal run with PostgreSQL orchestration
  state, including stage attempts, terminal outcome, correlation ID, and audit
  references; quarantine any mismatch.
- Recovery: restart/recovery evidence proves the n8n-owned path resumes from
  PostgreSQL authority without duplicate delivery or side effects.
- Fresh-volume: repeat the empty-inventory, parity, and recovery checks on a
  fresh-volume deployment and preserve the evidence artifact.

Only a separately approved decision may authorize Temporal removal after all
four checks pass. T153 live qualification is a separate gate and does not imply
T154 completion.
