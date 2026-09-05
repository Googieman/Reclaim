# Source-built REPLAY deployment

## Supported deployment

The supported runnable path is the local, deterministic, read-only REPLAY product.
It builds `reclaim/fs001-api:dev` and `reclaim/fs001-web:dev` from this repository,
starts fresh PostgreSQL migrations, and waits until all three containers are healthy.

```powershell
.\scripts\start-demo.ps1
```

Endpoints:

- Operator UI: `http://127.0.0.1:3000`
- API readiness: `http://127.0.0.1:8000/health/ready`
- API liveness: `http://127.0.0.1:8000/health/live`
- Canonical case: `http://127.0.0.1:3000/cases/case-canonical-demo-001`

The browser calls tenant-scoped API routes through the Next.js same-origin proxy.
It never receives the Docker-only `api:8000` hostname.

## Safety properties

- The launcher hard-codes REPLAY, the replay label, and both live-action switches off.
- The API refuses to mount the unauthenticated demo if production, LIVE, or either
  live-action setting is selected.
- The assembled demo API mounts read-only mode, replay, and operator-view routes;
  mutable approval, escalation, connector, and Action Gateway routes are absent.
- The operator view is labeled `authoritative=false` and `read_only=true`.
- A replay response always reports `side_effects=false` and no remote side effects.
- PostgreSQL migrations complete on a fresh volume and normalize webhook tables to
  the authoritative `public` schema. RLS remains forced on tenant tables.

## Operations

Production backup, restore, migration rehearsal, and safe recovery procedures are
documented in [backup-restore.md](backup-restore.md) and
[migration-rehearsal.md](migration-rehearsal.md). The declared operational targets
are RPO 15 minutes and RTO 60 minutes; these remain unqualified until a deployment-
owned rehearsal records measured timestamps.

Run the read-only release gate before deployment:

```powershell
.\scripts\release-preflight.ps1
```

See [release-readiness.md](release-readiness.md) for the gate contract, protected
production inputs, immutable release metadata, rollback path, and the unresolved
T153/T154 qualification requirements. A conditional result is not production
authorization.

Check health:

```powershell
.\scripts\status-demo.ps1
```

View logs:

```powershell
docker compose -p reclaim-demo -f infra\docker-compose.yml logs --tail 200
```

Stop without deleting data:

```powershell
.\scripts\stop-demo.ps1
```

The stop helper retains named volumes. To intentionally reset a failed or disposable
demo database, first verify the project name and volume, then use Docker Compose's
explicit volume-removal option. This destructive reset is not part of the normal
operator workflow.

## Troubleshooting

- If `localhost:3000` is unavailable, run the status helper and inspect `web` logs.
- If the API is unhealthy, inspect `api` logs and call `/health/ready` directly.
- If PostgreSQL initialization fails, inspect its logs for the first migration error;
  an accepting TCP socket alone is not proof that all migrations completed.
- If ports 3000 or 8000 are occupied, stop the conflicting process or set
  `RECLAIM_WEB_BIND` / `RECLAIM_API_BIND` to another loopback address as needed.
- A zero case count in PostgreSQL is normal for this replay deployment: the visible
  canonical case is a fixture, not authoritative merchant state.

## Not yet production-qualified

This deployment is not authorization for real merchant actions. Production requires
OIDC tenant roles, non-demo authoritative case repositories, Temporal workers,
the `infra/docker-compose.production.yml` overlay with deployment-provided
certificates and secret values, Redpanda mTLS/SASL/ACL enforcement, Vault-issued service credentials, qualified
evidence and action connectors, reconciliation/verification against merchant state,
deployment secrets, backups, monitoring, and environment-specific load/recovery
evidence. Live financial actions remain disabled until those gates are separately met.

The production overlay is deliberately fail-closed: it requires HTTPS identity
and Vault endpoints, a new n8n encryption key, and broker TLS/SASL inputs. Use
`infra/n8n/bootstrap.ps1 -Rotate -Activate` with a new
`RECLAIM_N8N_CREDENTIAL_REVISION` for staged n8n credential rotation. Verify the
workflow references and a smoke run before revoking the prior credential version.
