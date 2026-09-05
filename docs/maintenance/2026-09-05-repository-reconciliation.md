# Repository reconciliation — 2026-09-05

## Scope and preservation

The integration work was performed in the dedicated `codex/agent-chatbot-integration`
worktree. The planning checkout at `C:/Users/varug/.codex/worktrees/7082/Reclaim`
was left untouched, including its user-owned changes. No secrets, model weights,
raw evidence, provider credentials, or external deployment resources were used.

The sanitized inventory was captured before integration:

- The candidate worktree started from `origin/main` and was clean before branch creation.
- `origin/codex/hosted-final-round` contained migration, private-secret, hosted-runtime,
  and model-gateway work; the relevant commits were cherry-picked as reviewable commits.
- `origin/codex/railway-deployment` contained Docker `PORT`, exec-form healthcheck,
  and dependency fixes; those commits were cherry-picked and reconciled.
- The hosted and Railway refs remain remote history; this branch is the integration line.
- The source planning worktree contained unrelated dirty work and was not staged or reset.

## Disposition

| Area | Disposition | Result |
|---|---|---|
| Migration authority | keep/reconcile | `backend/db/migrate.py` is canonical; `backend/app/migrate.py` is a compatibility shim. Both use the same checksum ledger and advisory lock. |
| Hosted runtime and gateway | port | Hosted readiness, authenticated model transport, and provider-neutral gateway changes are present locally. |
| Railway Docker fixes | port | Dynamic `PORT`, exec-form healthchecks, and required dependency fixes are present locally. |
| Help model artifact | keep manifest only | GGUF metadata and preparation tooling are checked in; the 1.5B weights are external and were not downloaded. |
| Deployment | proposed, not provisioned | The private model service has a Railway-shaped artifact with no public domain or port. It is disabled by default. |
| Duplicate scripts/components | defer | Compatibility paths needed by Temporal drain and existing Fresh Agent tests remain. No cleanup deletion was performed. |

## Migration decision

Only the canonical runner may apply numbered SQL migrations. The compatibility
module delegates to it so existing imports do not create a second ledger. The
runner refuses modified checksums, uses a fixed transaction advisory lock, and
keeps `--check` read-only. Disposable-PostgreSQL migration execution and live
ledger transition remain deployment-owned gates; no production ledger was read or
modified here.

## Security scan boundary

The candidate adds only placeholders, manifests, source references, and tests.
`.gitignore` excludes GGUF/weight/cache artifacts and local model directories.
No populated `secrets/` file, model weight, raw evidence, or credential was added.

## Remaining release gates

T153/T154 live n8n/recovery evidence, private model resource qualification, held-out
investigation evaluation, and hosted identity/connector qualification remain open.
