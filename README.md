# RECLAIM

RECLAIM is a defense-only incident-intake, investigation, and containment
platform for merchant-controlled systems and approved connectors.

The repository contains a locally runnable operator product backed by
PostgreSQL, a deterministic replay path, an optional Fresh Agent analysis path,
typed policy and approval boundaries, an isolated Action Gateway simulator,
reconciliation and verification flows, append-only audit records, and the
supporting event/orchestration architecture.

## Current status

The supported runnable scope is local, synthetic, and safe by default. It does
not qualify live merchant execution or production deployment.

- Local PostgreSQL-backed operator flow: available.
- Deterministic REPLAY flow: available.
- Fresh Agent path: opt-in and advisory-only; model promotion is not approved.
- Documentation help path: locally wired, reviewer-authenticated, advisory-only,
  and disabled by default; the private DeepSeek candidate is not qualified or hosted.
- Live refunds, cancellations, payments, and other merchant effects: disabled.
- Render deployment: not yet configured or qualified in this repository.
- Release gate: currently conditional no-go until deployment-owned qualification
  and Temporal-drain evidence are complete.

The authoritative project status and remaining gates are recorded in
[`PROJECT_STATUS.md`](PROJECT_STATUS.md). The release checks are implemented in
[`scripts/release_preflight.py`](scripts/release_preflight.py).

The separate help profile and resource gate are documented in
[`docs/runbooks/model-services.md`](docs/runbooks/model-services.md). The checked-in
GGUF manifest contains integrity metadata only; model weights and secrets remain
outside the repository.

## What the local product demonstrates

The local operator flow uses a bounded synthetic merchant case. It demonstrates:

1. Incident intake into PostgreSQL.
2. Timeline and evidence reconstruction from authoritative rows.
3. Deterministic analysis and typed Fresh Agent proposals.
4. Policy evaluation and separated approval authority.
5. Action Gateway simulator execution with idempotency.
6. Unknown-result reconciliation and verification.
7. Escalation for inconclusive verification.
8. Append-only, evidence-linked audit history.

The synthetic fixture is clearly labelled as non-production data. The absence of
a configured model is reported as `MODEL_UNAVAILABLE`; the application does not
silently substitute a replay response for a failed Fresh Agent call.

## Architecture

The intended production boundaries are:

```text
Merchant evidence/connectors
            |
            v
      FastAPI intake  ---> PostgreSQL authority ---> operator APIs/UI
            |                         |
            v                         v
       n8n workflow             audit/replay/evaluation
            |
            v
      Redpanda events  ---> rebuildable Neo4j relationship projection

Approved typed proposals
            |
            v
    deterministic validation -> required approval -> isolated Action Gateway
                                                    |
                                                    v
                                      verification/reconciliation/audit
```

The repository follows these ownership rules:

- PostgreSQL owns business state, audit history, replay state, and evaluation
  state.
- n8n owns durable orchestration for new work.
- Redpanda carries asynchronous events.
- Neo4j is a rebuildable relationship projection, not the source of truth.
- Redis is coordination for n8n and is never the sole correctness boundary.
- The agent analyzes evidence and produces typed proposals only.
- Side effects require deterministic validation, versioned policy, approval,
  idempotent execution, verification, and audit.
- Financial values are calculated in integer minor currency units.

## Quick start on Windows

Prerequisites:

- Windows PowerShell.
- Docker Desktop configured for Linux containers.
- Docker Compose v2.
- Sufficient Docker resources for the full local profile and its supporting
  services.

From the repository root:

```powershell
.\scripts\start-demo.ps1
```

The launcher starts the local application and supporting services, including
PostgreSQL, Redpanda, Redis, MinIO, the event relay, n8n, the API, and the web
operator UI. It uses the Compose project name `reclaim-demo` by default.

Open:

- Operator UI: <http://127.0.0.1:3000>
- Case inbox: <http://127.0.0.1:3000/cases>
- API liveness: <http://127.0.0.1:8000/health/live>
- API readiness: <http://127.0.0.1:8000/health/ready>
- Canonical case: <http://127.0.0.1:3000/cases/case-canonical-demo-001>

Useful commands:

```powershell
# Show Compose state and API readiness
.\scripts\status-demo.ps1

# View recent logs
docker compose -p reclaim-demo -f infra\docker-compose.yml logs --tail 200

# Stop containers while retaining named volumes
.\scripts\stop-demo.ps1
```

Stopping the demo retains PostgreSQL and other named volumes. Do not remove
volumes as part of normal troubleshooting; an explicit disposable reset is a
destructive operation.

## Using the operator flow

After the UI loads:

1. Load the synthetic case into PostgreSQL when prompted.
2. Review the incident timeline, attribution labels, and financial exposure
   values.
3. Inspect the policy decision, proposal, approval history, and audit links.
4. Run Fresh Agent analysis if a model is configured. Without one, confirm the
   explicit `MODEL_UNAVAILABLE` result.
5. Approve through the local approval boundary.
6. Run the approved action in the deterministic simulator.
7. Inspect reconciliation, verification, terminal state, escalation, and audit
   provenance.

All local action results are simulator results. The local flow performs no
merchant payment, refund, cancellation, account mutation, or other remote
side effect.

## Fresh Agent configuration

The Fresh Agent path is disabled unless explicitly enabled by the local Compose
configuration. It uses the existing LangGraph/LiteLLM boundary and must return a
typed advisory result.

Set a LiteLLM-compatible provider before starting the demo when needed:

```powershell
$env:RECLAIM_SPECIALIST_MODEL = "your-model-name"
$env:RECLAIM_SPECIALIST_API_BASE = "http://127.0.0.1:8003/v1"
.\scripts\start-demo.ps1
```

Provider failures are surfaced explicitly. Model output cannot grant approval,
invent financial authority, or execute a connector action.

Read the [Fresh Agent operator guide](docs/operator/fresh-agent.md) and the
[FS-002 specification](specs/002-live-agent-specialization/spec.md) for the
full boundary and training/evaluation limitations.

## n8n workflow bootstrap

The checked-in n8n workflows are imported and activated separately because
credentials and service tokens must remain out of source control.

```powershell
$env:N8N_API_KEY = "<local-n8n-api-key>"
$env:RECLAIM_N8N_SERVICE_TOKEN = "<local-service-token>"
.\infra\n8n\bootstrap.ps1
```

See [`infra/n8n/README.md`](infra/n8n/README.md) for credential rotation,
workflow verification, and activation behavior.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI entry point, application services, repositories, policies, replay, workflows, connectors, and observability |
| `frontend/` | Next.js operator UI, same-origin API proxy, typed API client, and browser tests |
| `packages/contracts/` | Shared typed domain and API contracts |
| `infra/` | Docker Compose topology, PostgreSQL migrations, n8n, Redpanda, Vault, MinIO, backups, and observability configuration |
| `scripts/` | Local launcher/status helpers, validation, backup/restore, recovery, and release preflight tools |
| `tests/` | Unit, contract, integration, security, acceptance, browser, performance, and evaluation tests |
| `evaluation/` | Deterministic metrics and evaluation helpers |
| `training/reclaim/` | Dataset, split, training, serving, and promotion workflow artifacts |
| `docs/` | Architecture, operator, integration, deployment, backup, migration, and readiness documentation |
| `specs/` | Feature specifications, plans, decisions, data models, and task ledgers |
| `security-audits/` | Historical security-review artifacts and evidence; not runtime application data |

## Development setup

The backend targets Python 3.12 and the frontend targets Node.js 22.x.

Install backend dependencies from the repository root:

```powershell
python -m pip install -e ".\backend[test,dev]"
```

Install frontend dependencies:

```powershell
Push-Location frontend
npm ci
Pop-Location
```

For a fresh checkout, Docker Compose remains the most representative local
runtime because it supplies PostgreSQL and the supporting service boundaries.

## Validation commands

Run the relevant checks before changing deployment or safety behavior:

```powershell
# Python tests
python -m pytest

# Python lint and formatting
python -m ruff check backend tests evaluation packages
python -m ruff format --check backend tests evaluation packages

# Python import/bytecode smoke check
python -m compileall -q backend evaluation tests packages

# Repository-owned release gates (read-only)
python scripts/release_preflight.py
```

Frontend checks:

```powershell
Push-Location frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
Pop-Location
```

Tests that require PostgreSQL, Redpanda, n8n, MinIO, Vault, Neo4j, Redis,
Temporal, or a model provider are environment-gated. A skipped live-service
test is not evidence that the live service has been qualified.

## Configuration and secrets

Local examples live under [`infra/.env.example`](infra/.env.example) and the
Compose files. Never copy local development credentials into a hosted
environment.

Production configuration must provide, at minimum, deployment-owned values for
database access, OIDC issuer/audience/JWKS, Vault, broker SASL/TLS, n8n
encryption and service credentials, object storage, and service-to-service
identity. Live action switches must remain disabled until their explicit
qualification gates are approved.

Do not put real secrets in:

- Git-tracked `.env` files.
- `render.yaml` literal values.
- `NEXT_PUBLIC_*` frontend variables.
- Docker build arguments or image layers.
- prompts, evidence payloads, logs, audit narratives, or metrics labels.

## Deployment boundary

The repository currently supports the local Compose product, not a turnkey
Render production deployment. There is no committed Render Blueprint in this
checkout yet, and production requires separately provisioned or managed
services for PostgreSQL, object storage, identity, broker, orchestration,
secrets, observability, and worker execution.

Before any hosted deployment, complete the operator deployment guide and release
readiness gates:

- [Deployment guide](docs/operator/deployment.md)
- [Release readiness](docs/operator/release-readiness.md)
- [Backup and restore](docs/operator/backup-restore.md)
- [Migration rehearsal](docs/operator/migration-rehearsal.md)
- [T153 recovery validation](docs/validation/t153-fresh-volume-n8n.md)
- [FS-001 quickstart](specs/001-incident-intake-containment/quickstart.md)

The current local demo is deliberately not a production authorization. In
particular, do not enable live financial actions, deploy static demo tokens, or
interpret synthetic evaluation/training artifacts as production fraud
performance.

## Safety and data handling

RECLAIM is defense-only and operates only on merchant-controlled systems and
approved connectors. Evidence, model output, prompts, and external responses
are untrusted input.

The agent may analyze evidence and produce typed proposals. It must not directly
execute payments, refunds, cancellations, database writes, shell commands, or
arbitrary network calls. Side effects must pass the typed proposal, deterministic
validation, policy, approval, isolated execution, verification, and audit
sequence.

Refunds, when eventually qualified for a connector, must reference an existing
captured payment and return funds to the original payment source. An uncertain
remote result must be reconciled before retrying.

## Further reading

- [Product definition](PRODUCT.md)
- [Architecture overview](DESIGN.md)
- [Project status](PROJECT_STATUS.md)
- [FS-001 plan](specs/001-incident-intake-containment/plan.md)
- [FS-001 decisions](specs/001-incident-intake-containment/decisions/)
- [Reviewer workflow](docs/operator/reviewer-workflow.md)
- [Replay and escalation](docs/operator/replay-and-escalation.md)
- [Redpanda authority boundary](docs/integrations/redpanda-authority.md)
- [Training workflow](training/reclaim/README.md)
- [Hosted final-round completion plan](docs/superpowers/plans/2026-09-05-hosted-final-round-completion.md)
- [Hosted final-round design](docs/design/hosted-final-round.md)
- [API key setup and secret placeholders](secrets/README.md)
