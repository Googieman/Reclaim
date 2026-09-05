# Backup, restore, and recovery runbook

This runbook is the production-shaped procedure for the RECLAIM authoritative
state boundary. PostgreSQL is authoritative for business state. MinIO stores
immutable raw evidence and artifacts. n8n owns durable orchestration metadata;
Redis is only queue coordination and is never restored as business truth.

## Declared objectives

The current declared objectives are RPO 15 minutes and RTO 60 minutes. They are
configuration targets, not observed production results. The values are carried by
`RECLAIM_RPO_MINUTES`, `RECLAIM_RTO_MINUTES`, and
`RECLAIM_BACKUP_RETENTION_DAYS` (35 days by default) and must be supplied by the
production secret/configuration manager. A release gate may claim the objectives
only after a timestamped restore rehearsal measures them.

Static readiness means the policy, scripts, checksum manifest, alerts, and
runbooks are present and pass repository checks. Live qualification additionally
requires a real deployment-owned backup, an isolated restore, checksum and schema
verification, service recovery, and recorded elapsed RPO/RTO evidence. This
repository does not claim live qualification from static checks.

## PostgreSQL backup

Use an encrypted, access-controlled destination outside the repository. Do not put
credentials, raw incident narratives, or private evidence in the manifest.

```powershell
.\scripts\backup-postgres.ps1 `
  -ProjectName reclaim-production `
  -OutputDirectory D:\reclaim-backups\postgres
```

The procedure runs `pg_dump --format=custom`, writes a SHA-256 manifest, and runs
`pg_restore --list` before the artifact is accepted. Retain the dump and its
manifest together. A checksum mismatch quarantines the artifact; never restore it.

## MinIO backup

The evidence bucket must have versioning and object lock enabled before backup.
Configure the `mc` alias out of band; no access key is accepted as a script
argument or written to an artifact.

```powershell
.\scripts\backup-minio.ps1 `
  -SourceAlias reclaim-prod `
  -Bucket reclaim-evidence `
  -OutputDirectory D:\reclaim-backups\minio
```

The procedure verifies versioning, mirrors with `--preserve`, and writes a
manifest containing hashed object keys, object checksums, sizes, and an aggregate
checksum. The manifest intentionally does not persist raw object keys.

## Restore procedure

1. Declare an incident/change record and stop new intake or place the API in a
   maintenance state. Keep live actions and live financial actions disabled.
2. Verify the artifact and manifest SHA-256 values from the independent backup
   destination.
3. Restore PostgreSQL only into a new `reclaim_restore_*` database. The helper
   requires `-Confirm`, refuses an existing target, uses a single transaction, and
   never overwrites the authoritative database:

   ```powershell
   .\scripts\restore-postgres.ps1 `
     -ManifestPath D:\reclaim-backups\postgres\reclaim-postgresql-<stamp>.dump.manifest.json `
     -TargetDatabase reclaim_restore_<run_id> `
     -Confirm
   ```

4. Restore MinIO only into a new empty bucket with object lock/versioning enabled:

   ```powershell
   .\scripts\restore-minio.ps1 `
     -SnapshotPath D:\reclaim-backups\minio\minio-reclaim-evidence-<stamp> `
     -TargetAlias reclaim-restore `
     -TargetBucket reclaim-evidence-restore-<run_id> `
     -Confirm
   ```

5. Verify migration version, PostgreSQL RLS (including the isolated n8n schema),
   raw-object checksums, API readiness, and a read-only replay smoke. Rebuild
   Neo4j from PostgreSQL-backed events if required; do not treat the graph as
   authoritative. Redis may be recreated and reloaded by n8n.
6. Compare the elapsed recovery time and most recent verified backup timestamp
   with the declared RTO/RPO. Record actual values, environment, artifact IDs,
   checksum results, and unresolved gaps. Do not infer merchant correctness from
   process health alone.

## Recovery and uncertain results

Use `scripts/recovery-check.ps1` only for the preserved T153 project. It permits
restart of `api`, `n8n-worker`, and `redis` and checks readiness with live actions
disabled. It does not remove volumes or reset authoritative state. For a production
service outage, restart the named service through the deployment controller and
wait for readiness; n8n resumes from its durable execution state and PostgreSQL
stage attempts. Redis loss must not cause duplicate business mutations.

If an Action Gateway result is uncertain, reconcile the existing execution identity
before retrying. If verification remains ambiguous, preserve the state and escalate
to a human; never treat an unavailable dependency as successful containment.

## Alert response

Prometheus alerts are in `infra/observability/alerts.yml` and the dashboard is
`RECLAIM Operations`. For stale or failed backups, quarantine the artifact and
start a fresh backup after checking storage health. For PostgreSQL unavailability,
protect the last known authoritative state and follow the isolated restore process.
For stalled orchestration or recovery escalation, use the correlation ID, case ID,
workflow ID, and audit references to trace the failure without exporting raw
payloads, prompts, credentials, or narratives.
