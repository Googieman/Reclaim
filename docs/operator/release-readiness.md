# Release-readiness preflight

`release-preflight.ps1` is the deterministic, read-only repository gate for a
RECLAIM release. It checks the production Compose overlay, pinned runtime
versions, disabled live-action defaults, secret-manager input declarations,
backup/restore controls, health and observability artifacts, rollback guidance,
and the explicit T153/T154 qualification gates.

Run the static gate from the repository root:

```powershell
.\scripts\release-preflight.ps1
```

The command does not start containers, contact a merchant or provider, mutate
databases, inspect secret values, or print evidence. It returns:

- `0` and `DECISION: GO` only when every gate passes;
- `2` and `DECISION: CONDITIONAL NO-GO` when only deployment-owned evidence or
  qualification gates remain open; and
- `2` and `DECISION: NO-GO` when a repository control or supplied artifact is
  invalid. A checker/runtime error may return `1`.

## Deployment-owned inputs

The production overlay intentionally requires out-of-band secret-manager inputs
and immutable API/web image references. The image references must use a digest,
not a mutable tag.
To validate their presence without exposing values, pass a protected operator
file that is not committed:

```powershell
.\scripts\release-preflight.ps1 `
  -ProductionEnv D:\reclaim-secrets\release.env `
  -ReleaseMetadata D:\reclaim-release\release-metadata.json
```

The metadata JSON must contain a release identifier, a 40- or 64-character
source commit, SHA-256 API and web image digests, and the checked-in
`scripts/build_provenance.py` provenance producer. The preflight reports only
field-shape outcomes. It never prints the identifier, commit, digest, paths, or
secret values.

The production Compose overlay must continue to fail closed for missing
`KEYCLOAK_HOSTNAME`, OIDC, Vault, Redpanda TLS/SASL, n8n, and Keycloak database
inputs. Do not copy development values into a production input file. Secret
rotation and revocation remain deployment-manager operations after workflow
reference verification.

The preflight does not add a network-dependent SBOM, scanner, signing service,
or registry lookup. Image/source provenance is accepted only through the pinned,
repository-approved build provenance shape and deployment-supplied immutable
digests. A release must not substitute a mutable `latest`, `dev`, or unverified
image tag for those digests.

## Live checks and decision

Static health coverage checks the API liveness/readiness endpoints, container
healthchecks, Prometheus alerts, runbook links, and the operations dashboard. A
deployment owner must still run the safe Compose configuration check and health
smoke against the intended environment:

```powershell
docker compose `
  -f infra\docker-compose.yml `
  -f infra\docker-compose.production.yml `
  config --quiet
Invoke-RestMethod https://api.example.internal/health/live
Invoke-RestMethod https://api.example.internal/health/ready
```

Do not treat a process-health response as proof of merchant correctness,
financial execution, backup recovery, or model quality. Live actions and live
financial actions remain disabled until their separate typed approval, connector,
reconciliation, verification, and audit qualifications are approved.

T153 remains open until one preserved fresh-volume run proves n8n handoff,
duplicate delivery, model-unavailable handling, API/worker/Redis recovery, and
real desktop/mobile browser behavior with zero remote side effects. T154 remains
open until the fail-closed Temporal checklist records empty run inventory, parity,
recovery, and fresh-volume evidence. Keep Temporal and its SDK/services in place
while either gate is open.

## Rollback gate

Before migration, create verified PostgreSQL and immutable MinIO backups. If a
checksum, schema/RLS boundary, audit chain, n8n/PostgreSQL parity check, or
readiness check fails, stop intake, preserve evidence, and restore only into new
isolated targets using the documented helpers. Never overwrite the authoritative
database or an existing restore bucket, and reconcile uncertain Action Gateway
results before retrying. See [backup-restore.md](backup-restore.md) and
[migration-rehearsal.md](migration-rehearsal.md).
