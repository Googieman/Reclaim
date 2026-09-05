# RECLAIM Hosted Final-Round Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish and validate the complete hosted RECLAIM judge experience, with fresh advisory inference, durable recovery, isolated actions, OIDC and API-delivered private secrets.

**Architecture:** PostgreSQL remains authoritative, n8n owns new durable orchestration, Redpanda transports events and Neo4j is rebuildable. A private, mutually authenticated secrets broker reads Vault and delivers only each backend service's allowed credentials. The browser and advisory agent have no provider/action-secret access; the Action Gateway remains the only side-effect boundary.

**Tech Stack:** Existing Python/FastAPI, Next.js/TypeScript, LangGraph/LiteLLM, PostgreSQL, n8n/Key Value, Redpanda, S3-compatible storage, Vault/OIDC, Neo4j, OTel/Prometheus/Grafana/Loki, Langfuse, MLflow and Soup. Add Envoy for verified mutual-TLS termination at the broker and a migration runner using existing SQL migrations.

**Spec:** [Hosted final-round design](../../design/hosted-final-round.md), [ADR-006](../../../specs/001-incident-intake-containment/decisions/ADR-006-hosted-secret-delivery.md), and the existing FS-001/FS-002 plans and tasks. Read these together before execution.

## Global constraints

- PostgreSQL is authoritative for business state; n8n owns durable orchestration for new work; Redpanda carries asynchronous events; Neo4j is a rebuildable relationship projection; Redis is n8n queue coordination only and never a sole source of correctness.
- The LLM/agent may analyze evidence and produce typed proposals only.
- All side effects follow typed proposal, deterministic validation, versioned policy, required approval, isolated idempotent Action Gateway, verification, and audit.
- Perform financial calculations deterministically using integer minor currency units.
- Refunds may reference only an existing captured payment and must return funds to the original payment source.
- Reconcile an uncertain remote result before retrying; never double-refund or repeat a non-idempotent side effect.
- Audit history is append-only, evidence-linked, reproducible, and includes policy, approval, model, and execution versions.
- Synthetic or hybrid benchmark results must never be presented as real production fraud performance.
- Both `RECLAIM_LIVE_ACTIONS_ENABLED` and `RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED` stay false. Test Mode gets a distinct qualified switch, not a reuse of merchant-live flags.
- Terminal case states are `verified_contained`, `verified_failed`, and `escalated_unresolved`; an approval wait or `requires_attention` is not a successful terminal case.
- Secret placeholders explicitly requested by the user are allowed only as invalid setup examples. No real credential, private key or populated local file enters Git, image layers or browser output.
- No runtime service is deployed or provisioned by this planning change. Existing test results remain historical until rerun.

---

## How to execute and track this plan

This is the coordinated completion plan; each task produces an independently
reviewable deliverable. `CP01`-`CP11` are new completion work IDs, not replacements
for existing FS-001/FS-002 task IDs. Keep completed original tasks checked; record
remaining work here and cross-link evidence rather than rewriting history.

For behavior changes: add a focused failing regression, confirm the failure,
implement the smallest cohesive change, run the relevant unit/contract/integration/
failure/security/browser checks, inspect the diff, and commit only that task's
files. Broader release validation happens at CP11. Record actual outcomes and
skips in `PROJECT_STATUS.md` at each gate. Follow `frontend/AGENTS.md` and read the
installed Next.js documentation before frontend implementation.

Commands below run from the repository root unless a working directory is stated.
Use the project Python environment; the CI installation is
`python -m pip install -e "backend[test,dev]"`. New command names below are explicit
implementation deliverables, not claims that those scripts exist today.

### Work order and external dependencies

```text
CP01 T153 local qualification
  -> CP02 Temporal inventory and cleanup gate
  -> CP03 migrations/service roles
  -> CP04 private secret API and clients
  -> CP05 hosted composition and OIDC
  -> CP06 full fresh-analysis/approval/execution lifecycle
  -> CP07 Razorpay Test Mode connector qualification
  -> CP09 Render deployment
  -> CP10 operational/projection/evaluation surfaces
  -> CP11 hosted acceptance, recovery and final submission

CP08 specialist/data round 2 can run alongside CP03-CP07.
CP09 configuration work can proceed while CP08 runs; promotion is evidence-based.
CP02 cleanup is completed only after any missing CP06 parity is demonstrated.
```

The minimum first user-owned input is the n8n owner/bootstrap API key for CP01.
Before paid inference, select a provider/model and cost cap. Before provisioning,
fill workspace, region, budget and provider endpoints from
`secrets/deployment.example.json`. Before actual Test Mode API qualification,
provision the test key pair and webhook secret. The [secret setup guide](../../../secrets/README.md)
explains how to obtain each input. Do independent work while these inputs are
pending; do not manufacture credentials, resource IDs, test observations or costs.

## CP01: Close T153 with live, reproducible evidence

**Files:** inspect/modify `scripts/validate-t153.ps1`, `infra/n8n/bootstrap.ps1`,
`infra/n8n/workflows/incident-analysis-handoff.v1.json`,
`infra/n8n/workflows/incident-analysis-error-recovery.v1.json`,
`tests/acceptance/test_t153_n8n_runtime.py`,
`tests/acceptance/test_t153_restart_recovery.py`, `tests/support/t153_runtime.py`,
`frontend/playwright.t153.config.ts`, `docs/validation/t153-fresh-volume-n8n.md`.

**Consumes:** existing isolated harness, source images, n8n owner API key,
Kafka credential configuration and tenant-scoped RECLAIM service token.
**Produces:** sanitized proof of real Kafka -> n8n -> PostgreSQL -> browser
progress, duplicate handling and restart recovery; closes original T153 only on pass.

- [ ] Inspect the preserved project/volume identity and current harness record;
  resume it if valid. If a new fresh-volume run is needed, prepare a uniquely
  named isolated project. Do not delete or reuse the shared demo's volumes.
- [ ] Obtain the bootstrap key through the operator-owned secret channel. Run
  the existing harness with real project/run IDs. Keep all secret values out of
  command arguments/transcripts and persistent artifacts.

```powershell
# Set $validationProject to the verified existing harness project name.
pwsh -NoProfile -File scripts/validate-t153.ps1 -Run -ProjectName $validationProject
```

- [ ] If the recorded Kafka parsing/activation failure persists, reproduce it
  against the pinned n8n version, capture a redacted failure, add the regression
  beside existing n8n tests, then fix the exact credential/workflow adapter.
- [ ] Require duplicate input to retain one authoritative run and no duplicate
  model/action work. Interrupt worker/API/Redis independently, recover, and prove
  the expected state from PostgreSQL instead of n8n execution status alone.
- [ ] Run the full T153 desktop/mobile browser suite with no mocked routes. Test
  model unavailability explicitly. Persist source versions and the actual test
  totals, including failures/skips, then update T153 and project status.

**Review gate:** all required live cases execute and pass; an inactive workflow,
missing secret, skipped external test or non-terminal expected outcome keeps the
gate open. Retain sanitized artifacts for a reviewer to reproduce.

## CP02: Resolve Temporal drain without removing unfinished behavior

**Files:** `docs/operator/migration-rehearsal.md`,
`specs/001-incident-intake-containment/decisions/ADR-004-n8n-orchestration-boundary.md`,
`backend/workflows/`, `backend/pyproject.toml`, `infra/docker-compose.yml`,
`infra/versions.env`, FS-001 `tasks.md`; create
`docs/validation/t154-temporal-drain.md` and, only after evidence,
`specs/001-incident-intake-containment/decisions/ADR-007-temporal-retirement.md`.

**Consumes:** CP01 evidence and actual inventories for every legacy namespace/
task queue used by this installation. **Produces:** a supported legacy disposition
and an explicit removal decision; no new Temporal runs are admitted.

- [ ] Record namespace/queue identifiers, open/running/pending legacy workflows,
  PostgreSQL references and the new-work owner gate with timestamps.
- [ ] Build a parity matrix for evidence, analysis, approval wait/resume,
  execution, reconciliation, verification, escalation and failure recovery.
  Missing post-approval n8n coverage is completed in CP06 before cleanup.
- [ ] Drain valid existing work using its documented behavior; account for every
  unresolved item. Never cancel an unknown financial outcome to empty an inventory.
- [ ] After empty inventory, CP01 and CP06 parity/recovery evidence all pass,
  record ADR-007; remove runtime Temporal services/imports/dependencies and update
  package metadata/tests. Keep historical migration evidence and audit records.
- [ ] Rebuild the package and run import/source-container and lifecycle tests.

```powershell
rg -n 'temporalio|TEMPORAL_TARGET|temporal:' backend infra .github
python -m pytest tests/acceptance/test_safe_containment.py tests/acceptance/test_fs001_complete_flow.py -q
```

**Review gate:** no runtime dependency on Temporal for new or existing supported
work; historical references can remain. Close T154 only with an evidenced cleanup,
not simply because a search no longer finds the SDK.

## CP03: Production database, storage and migration foundations

**Files:** existing `backend/db/migrations/001_*.sql` through `013_*.sql`,
`backend/app/db/unit_of_work.py`, `backend/app/storage/minio_evidence.py`,
`backend/pyproject.toml`; create `backend/db/migrate.py`,
`backend/db/migrations/014_hosted_service_roles.sql`,
`tests/integration/test_hosted_migrations.py`,
`tests/integration/test_hosted_storage.py`, `docs/operator/hosted-data-bootstrap.md`.
Use the next unused migration number if another change has claimed `014`.

**Consumes:** PostgreSQL administration supplied only to the deployment job and
selected private object storage. **Produces:** repeatable migrations and distinct
least-privilege DB roles, plus a verified evidence-storage adapter.

- [ ] Add a migration ledger `(version, checksum, applied_at)` and a fixed
  PostgreSQL advisory lock. Reject a modified already-applied migration; apply
  each unapplied migration transactionally where supported. Document separately
  any statement that cannot be transactional. Never run migrations on every API start.
- [ ] Implement the command contract below. `--check` is read-only and returns
  nonzero for pending/checksum-mismatched migrations; normal invocation applies
  migrations with the deployment role only.

```text
python -m db.migrate --check
python -m db.migrate
```

- [ ] Provision API, gateway, relay, projection, secret-audit, n8n, Keycloak and
  MLflow roles/database ownership. n8n/Keycloak/MLflow roles cannot select RECLAIM
  tables. API/gateway do not inherit migration privileges or bypass tenant RLS.
  Seed only the explicit synthetic tenant/operator setup, not demo credentials.
- [ ] Add `secret_access_events` with event ID, caller identity, tenant/scope,
  secret ID/version, request ID, timestamp and outcome, but no secret payload.
  Give the broker audit role INSERT-only access; record intent and delivery as
  separate appended events, not updates to an earlier row.
- [ ] Exercise a fresh database, upgrade from current schema, second no-op run,
  two concurrent runners, and interruption. Verify the ledger and tenant grants
  after each case. Restore a pre-migration backup into an isolated database.
- [ ] Test the chosen S3-compatible provider for checksums, concurrent create,
  duplicate object handling, tenant prefixes and retention/version behavior;
  fix the adapter for the actual provider instead of assuming API compatibility.

Example migration assertion to include in the real DB fixture test:

```python
def assert_single_application(rows: list[tuple[str, str]]) -> None:
    versions = [version for version, checksum in rows]
    assert len(versions) == len(set(versions))
    assert all(checksum for version, checksum in rows)
```

**Run:** `python -m pytest tests/integration/test_hosted_migrations.py tests/integration/test_hosted_storage.py -q`.
**Review gate:** migrations/grants and immutable storage work on real selected
dependencies; replay fixtures do not satisfy this hosted-data gate.

## CP04: Implement the private secrets broker and runtime clients

**Files:** create `backend/secret_broker/__init__.py`, `contracts.py`, `policy.py`,
`service.py`, `main.py` in that package; create
`backend/app/secrets/broker_client.py`, `runtime_loader.py`,
`infra/secret-broker/Dockerfile`, `envoy.yaml`, `entrypoint.sh`,
`scripts/provision-secrets.py`, `tests/contract/test_secret_broker.py`,
`tests/security/test_secret_broker_access.py`,
`tests/integration/test_secret_broker_rotation.py` and
`tests/integration/test_secret_broker_network.py`.
Modify `backend/app/secrets/vault.py`, `infra/vault/policies/`,
`backend/pyproject.toml`, `tests/security/test_vault_scopes.py` and `secrets/README.md`.

**Consumes:** CP03 audit persistence; ADR-006; template bundle/policy IDs; service
certificate bootstrap and Vault endpoint/auth. **Produces:** only
`POST /v1/secrets/resolve`, authorized by verified service identity and tenant,
and a secret client with bounded in-memory caching.

- [ ] Implement strict versioned contract types; unknown fields are rejected.
  Keep secret values out of `repr`/exception output. The client returns secrets
  only inside trusted service code, never serializes them into product objects.

```python
from pydantic import BaseModel, ConfigDict, Field, SecretStr

class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret_id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)

class SecretBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret_id: str
    version: int = Field(ge=1)
    cache_ttl_seconds: int = Field(ge=1, le=300)
    values: dict[str, SecretStr]
```

Service-scoped requests omit `tenant_id`; tenant-scoped records require an exact
allowed tenant. The server must serialize `SecretStr` values explicitly only on
the authenticated secret-response path; default masked JSON is not a valid
delivery implementation. Everywhere else retains redacted serialization.

- [ ] Implement exact identity/secret/tenant mapping from a validated installed
  policy; reject example policies and path overrides. Preserve separate action
  and webhook Vault paths. Unknown/forbidden IDs give indistinguishable `403`s.
- [ ] Configure mutual TLS and verified identity forwarding exactly as ADR-006.
  Bind the application to loopback and separate its private health listener.
  Validate both supervised processes, hostname verification and actual peer SANs.
- [ ] Implement scoped Vault reads, audit-before-release, per-identity rate
  limits, read timeouts and redaction. Use at most 60-second action / 300-second
  other caches; do not pretend cache expiry revokes a provider key.
- [ ] Implement the operator-only provisioning CLI. It rejects `template_only`,
  missing enabled fields and both invalid sentinel prefixes, restricts target
  paths to policy, supports metadata-only dry run, and never prints values.

```text
python scripts/provision-secrets.py --input secrets/runtime.local.json --dry-run
python scripts/provision-secrets.py --input secrets/runtime.local.json --apply
```

- [ ] Implement startup loaders for Python and n8n. Map bundle fields to existing
  `RECLAIM_*`, `DB_POSTGRESDB_*` and queue settings in process memory; translate
  Key Value URLs into pinned n8n host/port/auth/TLS options. Only file-requiring
  values get private runtime files. Bootstrap/migration identities are distinct.
  Do not issue short-lived DB/queue leases to an n8n process that cannot renew
  them. Test controlled restart/credential update for static startup settings
  separately from API-client cache expiry and OAuth2 access-token refresh.
- [ ] Test public non-reachability; a private client with no cert; forged identity
  header; cross-tenant request; revoked cert; unknown secret; placeholder input;
  Vault/audit outage; TTL expiry; and rotation during an uncertain action. Search
  telemetry/browser artifacts for canary values used by the integration tests.

```powershell
python -m pytest tests/contract/test_secret_broker.py tests/security/test_secret_broker_access.py tests/security/test_vault_scopes.py tests/integration/test_secret_broker_rotation.py tests/integration/test_secret_broker_network.py -q
```

**Review gate:** the API can obtain its evidence/webhook credentials but cannot
obtain `razorpay.test.action`; only the gateway can. The agent and BFF have no
broker grant. Actual transport tests, not only mocked policy functions, pass.

## CP05: Assemble the hosted runtime and real OIDC login

**Files:** `backend/api/main.py`, `backend/app/config.py`, `backend/app/auth/oidc.py`,
`backend/api/approvals.py`, `backend/api/operator_view.py`,
`frontend/next.config.mjs`, `frontend/src/lib/config.ts`, `frontend/Dockerfile`,
`infra/keycloak/realm-reclaim.json`; create `backend/app/runtime.py`,
`frontend/src/lib/server/session.ts`, `frontend/src/lib/server/api-gateway.ts`,
`frontend/src/app/auth/login/route.ts`, `auth/callback/route.ts`,
`auth/logout/route.ts` under the same app directory,
`frontend/src/app/api/reclaim/[...path]/route.ts`,
`tests/integration/test_hosted_runtime.py`,
`tests/security/test_hosted_identity.py`, `frontend/e2e/hosted-auth.spec.ts`.

**Consumes:** scoped CP03 roles, CP04 secret client, OIDC issuer/JWKS/audience and
separate human/service identities. **Produces:** a hosted application factory and
server-side browser session gateway with no local-demo dependency.

- [ ] Add separate service settings for API, model, gateway, broker and workers;
  do not require every service to load every credential just to pass global
  settings validation. Preserve rejection of unqualified merchant-live actions.
- [ ] Construct PostgreSQL UoWs, storage, inbox/intake, orchestration, policy,
  approval, verification/escalation and audit read models in `app/runtime.py`.
  Mount every required product route using those dependencies with demo flags
  false. Make readiness check the required DB/schema/configuration rather than
  running canonical replay; never report PostgreSQL healthy from replay success.
- [ ] Replace build-time demo credentials and static rewrite routing with a
  runtime server-side BFF. Use an audited OIDC client compatible with the installed
  Next.js release: authorization code with PKCE, state and nonce verification,
  exact redirect allowlist, Secure/HttpOnly/SameSite cookies, token refresh and
  logout. Store tokens server-side in a scoped session store or authenticated
  encrypted cookie; never store them in browser localStorage or public config.
- [ ] Implement exact path/method forwarding for product APIs; exclude secret,
  metrics, service orchestration and admin routes. Reject encoded traversal,
  absolute URLs, client-selected upstreams and redirect-following to internal
  services. Strip client-supplied identity headers; derive identity from session.
- [ ] Verify JWT issuer/audience/RS256/JWKS/expiry/tenant/role on the API as well
  as the BFF. Apply CSRF and Origin validation to cookie-authenticated writes;
  validate approver separation and approval expiry server-side.
- [ ] Test login/logout/expired session, wrong-tenant case IDs, unauthorized
  approval, spoofed headers, blocked secret proxy paths, missing DB and startup
  without credentials. Run real OIDC browser tests in the isolated stack.

```powershell
python -m pytest tests/integration/test_hosted_runtime.py tests/security/test_hosted_identity.py tests/security/test_oidc_tenant_roles.py tests/security/test_approval_separation.py -q
```

**Frontend verification (working directory `frontend`):** `npm run typecheck`,
`npm run lint`, `npm test -- --run`, `npm run build`, then the hosted-auth
Playwright suite against real OIDC. **Review gate:** authenticated product routes
work from a fresh image without any `NEXT_PUBLIC_DEMO_*` credential.

## CP06: Complete fresh analysis through terminal recovery

**Files:** `backend/agent/fresh_run.py`, `langgraph_harness.py`, `model_profiles.py`,
`litellm_gateway.py`, `backend/app/orchestration/service.py`,
`backend/api/orchestration.py`, `backend/api/workflow_commands.py`,
`backend/action_gateway/service.py`, `reconciliation.py`, `verification.py`,
`packages/contracts/orchestration.py`, `infra/n8n/bootstrap.ps1`;
create `backend/agent/server.py`, `backend/model_gateway/__init__.py`,
`backend/model_gateway/server.py`, `backend/action_gateway/server.py`,
`infra/n8n/workflows/incident-terminal-recovery.v1.json`,
`tests/acceptance/test_hosted_lifecycle.py`,
`tests/security/test_hosted_agent_boundary.py`,
`tests/integration/test_approval_resume.py` and package them explicitly.

**Consumes:** CP05 typed/persisted services, CP04 per-service identities, selected
fresh provider, existing deterministic action/policy contracts. **Produces:**
durable case progress through all judge-facing stages, including after approvals.

- [ ] Add an authenticated typed agent service and a separate trusted model
  transport service. Keep existing `ModelProvider` compatibility; replace direct
  provider-key resolution in the runner with an internal transport. The model
  gateway alone resolves `model.provider`; disable arbitrary base URLs/models
  supplied in evidence or prompts. Apply budgets, redaction and strict schema
  parsing; record actual provider/model/version, latency, usage and cost source.
- [ ] Version the additional orchestration stage contracts and workflow artifacts.
  Connect evidence -> timeline -> attribution/exposure -> fresh analysis ->
  deterministic policy -> human handoff through allowlisted RECLAIM APIs. n8n
  has no database/model/action credentials and cannot approve its own proposal.
- [ ] Publish approval outcomes through the transactionally persisted outbox.
  Resume the case via an idempotent typed command. The API verifies approval and
  dispatches an approved action identity to the separate gateway, which rechecks
  tenant, exact proposal/policy version, expiry, bounds and idempotency.
- [ ] Persist every stage ownership/attempt transition before acknowledgement.
  Duplicate events and restarted workflows must resume the same logical action.
  Implement reconciliation/verification/escalation stages; a provider timeout
  becomes UNKNOWN and cannot be turned into a blind repeated mutation.
- [ ] Give n8n a client-credentials OAuth2 identity with refresh, replacing a
  long-lived human/static service token in hosted workflows. Keep the existing
  bootstrap adapter compatible with the pinned n8n API and evidence-safe rotation.
- [ ] Exercise fresh input, duplicate delivery, approval wait/restart, denied/stale
  approval, provider outage, unknown result, verification failure, escalation and
  cross-tenant access. Assert a stored action ID/count, not just a green workflow.

Acceptance evidence record for a single scenario must include these fields:

```json
{
  "scenario": "restart-after-approval",
  "source_commit": "git SHA recorded by the harness",
  "case_id": "ID returned by the real intake call",
  "workflow_version": "version observed on the active workflow",
  "run_mode": "fresh_agent",
  "action_environment": "simulator",
  "authoritative_action_count": 1,
  "terminal_state": "verified_contained",
  "assertions_passed": true
}
```

This is the output contract, not an observed result to copy into a report.

**Run:** `python -m pytest tests/acceptance/test_hosted_lifecycle.py tests/security/test_hosted_agent_boundary.py tests/integration/test_approval_resume.py -q`.
**Review gate:** the complete lifecycle persists and recovers through real n8n;
fresh provider failures remain visible and do not silently run replay. Revisit
CP02's Temporal parity matrix before removal.

## CP07: Qualify actual Razorpay Test Mode without claiming unsupported actions

**Files:** `backend/connectors/razorpay/actions.py`, `manifest.py`, `webhook.py`,
`backend/action_gateway/controls.py`, `network_policy.py`, `reconciliation.py`,
`backend/app/config.py`, `docs/integrations/razorpay-test-mode-actions.md`;
create `backend/connectors/razorpay/http_client.py`,
`frontend/src/app/api/webhooks/razorpay/route.ts`,
`tests/contract/test_razorpay_test_transport.py`,
`tests/integration/test_razorpay_test_mode_live.py`,
`docs/validation/razorpay-test-mode-qualified.md`.

**Consumes:** CP06 approved actions; Test Mode key pair delivered only to gateway;
separate signature-verification secret delivered only to intake API.
**Produces:** an explicitly gated Test Mode adapter, or an honestly recorded
integration dependency while simulator demonstration remains available.

- [ ] Verify the current official API methods, response states, webhook retry
  behavior and idempotency guarantees for each selected payment/refund operation
  before coding the HTTP client. Store links and verified date in the runbook.
  Do not assume refund receipt fields or a generic idempotency header guarantee
  uniqueness unless the chosen endpoint documents it.
- [ ] Add the distinct Test Mode qualification flag/manifest, fixed HTTPS provider
  destination and credential checks. Reject `rzp_live_` keys and caller-defined
  URLs. Fetch authoritative captured-payment state and record a verified
  provider-to-case mapping before allowing a refund proposal to reach execution.
- [ ] Preserve original webhook body bytes through the BFF, with bounded size
  and exact signature verification. Never forward arbitrary upstream URLs or
  derive authoritative payment mapping from caller-supplied case IDs.
- [ ] Keep a durable pending execution before the provider request. On timeout,
  reconcile using exact provider identity and payment/refund facts. If uniqueness
  cannot be established, escalate and stop; an empty initial lookup is not by
  itself evidence that a delayed provider mutation did not happen.
- [ ] Verify the final provider state before marking containment. Keep non-payment
  session/fulfillment operations in the merchant simulator unless their actual
  connector has been implemented and qualified separately.
- [ ] Run contract/error tests locally, then the explicitly configured Test Mode
  integration against captured test payments: duplicate dispatch, lost response,
  partial/already refunded, wrong tenant/currency/source, webhook duplicate and
  malformed signature. Record provider request/resource IDs with no secrets.

**Run:** `python -m pytest tests/contract/test_razorpay_test_transport.py tests/security/test_refund_safety.py tests/integration/test_razorpay_test_mode_live.py -q`.
**Review gate:** genuine Test Mode calls are supported by evidence. If the live
integration tests skip, keep the release simulator-labeled and the Test Mode
checkbox open; never label a fixture response as a provider integration.

## CP08: Complete the specialist/data round 2 and select honestly

**Files:** `training/reclaim/scripts/build_dataset.py`, `validate_dataset.py`,
`splits.py`, `evaluate.py`, `promotion.py`, `training/reclaim/configs/reclaim-sft.yaml`,
`training/reclaim/manifests/`, `training/reclaim/evals/`,
`tests/evaluation/test_agent_dataset_splits.py`; create
`training/reclaim/scripts/collect_responses.py`,
`training/reclaim/data/sources/round2-source-manifest.json`,
`training/reclaim/evals/round2/README.md`.

**Consumes:** approved synthetic/merchant-controlled source fixtures, CP06 provider
contract, training compute and optional restricted artifact access.
**Produces:** real round-2 training and evaluation provenance; measured baseline/
specialist decision, not a promised win for a specialist.

- [ ] Record approved source/license/provenance and create independent entity/time
  groups before generating variants. Target at least 500 cases where feasible,
  grouped 60/20/20 and at least 100 held-out cases. Enforce >=25% no-compromise
  cases and >=30% mixed legitimate/malicious cases among compromised examples.
  Do not duplicate one source case across partitions or fabricate rows to hit counts.
- [ ] Keep validation for candidate/prompt/hyperparameter selection. Freeze model,
  prompts, tool budgets and policies before the sealed held-out comparison. Do
  not inspect held-out errors and tune against the same held-out set repeatedly.
- [ ] Extend response collection to call each real provider on the same selected
  split and budgets; store private redacted outputs with hashes and run manifests.
  Each record identifies case, profile, raw/parsed output, error, usage and latency.

```text
python training/reclaim/scripts/collect_responses.py --profile reclaim-baseline --manifest training/reclaim/manifests/dataset.json --split validation --output training/reclaim/data/generated/base-validation.jsonl
```

- [ ] Run the existing dataset validator and baseline evaluator with actual
  response files. Audit available Soup/torch/CUDA compute, select a model that
  fits measured capacity, then run the configured SFT job and serving probe.
  Record exact model/tokenizer/checkpoint hashes, config, seed and observed steps.
- [ ] Freeze finalists, run the same sealed evaluation for baseline/specialist,
  and execute promotion with complete matching manifests. Include confidence
  intervals, precision/recall, contained/disrupted value, resolution, tool usage,
  injection/forbidden outcomes, schema validity, latency and model cost.

```text
python training/reclaim/scripts/validate_dataset.py --dataset training/reclaim/data/generated --manifest training/reclaim/manifests/dataset.json
python training/reclaim/scripts/promotion.py --base training/reclaim/evals/base.json --specialist training/reclaim/evals/specialist.json --output training/reclaim/evals/comparison.json --training-manifest training/reclaim/manifests/training-run.json
```

- [ ] Deploy the chosen measured profile behind CP06's model gateway; authenticate
  a specialist endpoint and measure its startup/memory/latency. An unpromoted
  specialist stays available only as an explicitly experimental comparison.

**Review gate:** actual responses, sealed split integrity and observed reports
exist. `DON'T SHIP` is a valid honest specialist outcome; leaving evaluation
`not_run` or treating training loss as fraud quality does not complete the task.

## CP09: Build reproducible containers and the full Render topology

**Files:** `backend/Dockerfile`, `frontend/Dockerfile`, `backend/pyproject.toml`,
`.dockerignore`, `.github/workflows/ci.yml`, `.github/workflows/security.yml`,
`scripts/release_preflight.py`, `docs/operator/deployment.md`;
create `render.yaml`, `infra/render/service-inventory.json`,
`infra/render/service-entrypoint.sh`, `infra/render/n8n-entrypoint.sh`,
`infra/render/ports.json`, `docs/operator/render-deployment.md`,
`tests/integration/test_render_topology.py`.

**Consumes:** CP03-CP06 deployable services, provider choices and credential
provisioning; CP07/CP08 qualification state is represented explicitly.
**Produces:** validated infrastructure configuration and a reachable staging stack
with private service identities and a recorded release revision.

- [ ] Install declared/pinned package dependencies in backend images, including
  actual runtime imports such as metrics and Vault. Add new packages to the
  explicit setuptools list. Keep non-root users; verify clean image imports and
  required wheels/native runtime libraries. Resolve build/CI/runtime version drift
  and review pinned dependencies before internet exposure.
- [ ] Remove frontend demo-token build arguments and bake no credential into any
  stage. Images start without populated `secrets/`; deploy-mounted bootstrap
  files are runtime inputs only. Source-folder exclusion is tested in build context.
- [ ] Declare each service from the hosted design with exact Docker commands and
  ports: public web; private API, agent, model gateway, Action Gateway, secrets,
  n8n main, MLflow and collector; n8n/relay/projection workers; PostgreSQL and Key
  Value. Pin/version infrastructure. Include Keycloak/Vault private deployment
  definitions if using self-hosting, with separately restricted login/admin ingress.
  External Redpanda/S3/Neo4j/Langfuse/telemetry endpoints appear in inventory.
- [ ] Validate Render's current supported private ports before setting them;
  use explicit non-restricted listeners (for example API `8000`, n8n `5678`,
  broker `8443` and health `8081`). A public web process binds `0.0.0.0:$PORT`.
  Match health ports/start commands and discover internal hosts; `hostport` is
  not a complete URL and may require an explicit protocol.
- [ ] Wire only bootstrap trust/identity plus non-secret configuration into
  application services. Scope Render env groups; never give a shared all-secret
  group to every service. `fromDatabase` admin credentials belong to a one-shot
  provision/migrate operation; runtime roles are supplied through Vault/broker.
- [ ] Execute the startup dependency sequence: data/Vault -> DB roles/migrations
  -> identity certificates and broker -> app/gateways -> n8n -> workflow imports
  and activation -> public frontend/webhook routes. Supply unique n8n DB/encryption
  values before startup and test credential refresh. Disable uncontrolled
  auto-deploy until migration/credential dependency ordering is verified.
- [ ] Confirm chosen plans and measured resource needs fit the user-supplied
  spending cap before creating resources. Record actual plan pricing at execution
  time, not an invented estimate here. A private Vault or other disk service
  needs an explicit restart/restore and availability decision.
- [ ] Validate Blueprint with Render CLI, run image/topology smoke tests, publish
  the reviewed deployment files to the requested GitHub repository and deploy the
  selected revision through the configured account. Keep deploy credentials in
  the operator/CI context only.

```text
render blueprints validate
python -m pytest tests/integration/test_render_topology.py -q
python scripts/release_preflight.py
```

**Review gate:** an actual service inventory ties host/type/version to health;
broker/API/admin services are private as specified. Blueprint validation alone
does not establish working OIDC, migrations, queues or secret delivery.

## CP10: Finish graph, observability, audit and operational evidence

**Files:** `backend/projections/neo4j_projection.py`, `neo4j_case_projection.py`,
`backend/app/observability/telemetry.py`, `metrics.py`, `redaction.py`,
`backend/observability/evaluation.py`, `infra/langfuse/`, `infra/mlflow/`,
`docs/operator/backup-restore.md`, `docs/operator/release-readiness.md`;
create `backend/projections/worker.py`, `infra/observability/hosted-collector.yaml`,
`docs/operator/hosted-operations.md`, `tests/integration/test_hosted_observability.py`.

**Consumes:** persisted case/event/audit/model data and CP09 services.
**Produces:** observable runtime relationships, reproducible graph projection,
linked model/evaluation provenance and tested restoration procedures.

- [ ] Wire a real projection consumer, tenant-scoped graph writes, checkpointing
  and rebuild command. Prove graph unavailability does not change exposure,
  approvals or action correctness. Rebuild and compare against authoritative data.
- [ ] Propagate tenant/case/run/trace/action identifiers through API, n8n calls,
  model gateway, outbox and gateway. Export redacted traces/logs/metrics with
  model bodies and secret payloads excluded; bound high-cardinality metric labels.
- [ ] Connect dashboards and alerts for queue/outbox lag, stuck orchestration,
  UNKNOWN actions, failed verification, dependency outage, secret lease/cert expiry,
  provider latency/cost and backup age. Run one real alert-path exercise.
- [ ] Populate Langfuse with actual redacted run traces and MLflow with actual
  CP08 manifests/checkpoint hashes/evaluation artifacts. Show unavailable optional
  exporters explicitly and queue bounded retries; they cannot authorize actions.
- [ ] Expose authenticated audit/provenance read models for judges; verify audit
  chain tamper detection and link evidence/policy/approval/model/execution versions.
  Keep operational dashboards and administrative consoles access-controlled.
- [ ] Restore PostgreSQL, evidence metadata/objects and required Vault state into
  an isolated target; restore n8n with the same encryption key; resume a waiting
  case and reconcile any uncertain action before dispatch. Rebuild Neo4j rather
  than treating it as an authoritative backup. Measure actual RPO/RTO against
  configured targets (`15`/`60` minutes initially) and report misses honestly.

**Run:** `python -m pytest tests/integration/test_hosted_observability.py -q`, then
the documented real backup/restore rehearsal with sanitized evidence.
**Review gate:** real traces, graph queries, model/evaluation artifacts and restore
outcomes exist; running containers and empty dashboards are not completion.

## CP11: Hosted qualification and final judge submission

**Files:** create `scripts/qualify_hosted.py`,
`tests/acceptance/test_hosted_final_round.py`,
`frontend/e2e/hosted-final-round.spec.ts`, `frontend/playwright.hosted.config.ts`,
`docs/validation/hosted-final-round.md`, `docs/operator/judge-demo.md`;
modify `README.md`, `PROJECT_STATUS.md`, `docs/operator/release-readiness.md` and
release-preflight contracts to account for hosted-final vs merchant-production gates.

**Consumes:** CP01-CP10 evidence, final URL, independent judge/operator accounts,
actual credential/connector/model qualification state and a pinned release.
**Produces:** reproducible final demo and a truthful hosted release decision.

- [ ] Implement the hosted qualification command. `--scenario` selects one
  allowlisted scenario, `--output` writes sanitized evidence, and fixture users/
  URLs come from private runner configuration. No secrets in command arguments.
  Emit the CP06 record plus dependency versions, assertions, durations, failures
  and skip reasons. Non-executed required scenarios return nonzero.

```text
python scripts/qualify_hosted.py --scenario all --output tmp/hosted-final/evidence.json
```

- [ ] Exercise real browser login -> new incident -> n8n -> fresh analysis ->
  malicious/legitimate/uncertain timeline -> deterministic exposure -> policy ->
  separate approver -> action -> reconciliation -> verified terminal/escalation
  -> audit links. Cover desktop and mobile; no route mocks in hosted acceptance.
- [ ] Exercise duplicate intake/delivery/action request, model outage, restart
  while awaiting approval, lost provider response, broker/Vault outage, expired
  credential/session and cross-tenant request. Probe public routes for accidental
  access to broker, docs, metrics, secret files and internal proxy destinations.
- [ ] Run the full relevant backend/frontend regression once after all behavior
  changes settle. Run real external dependency gates and label every skip. Record
  measured performance instead of converting provisional targets into successes.
- [ ] Run release preflight for an explicit `hosted-final` profile. It checks all
  F01-F13 requirements, service identities, broker qualification and real fresh
  inference. Test Mode provider evidence is required only if advertised; merchant
  production remains a separate unqualified profile with live actions disabled.
- [ ] Produce the judge script: normal scenario, denied/uncertain scenario,
  architecture walk-through, n8n/trace/audit/evaluation evidence, model decision,
  reset-to-new-synthetic-case instructions and known limits. Update README with
  actual deployed URLs and credential-free startup/operator documentation.
- [ ] Capture deployed commit/image/workflow/model/policy versions, evidence
  checksums, backup/restore results and remaining limitations. Publish only
  sanitized source/docs/evidence to GitHub; keep account passwords/tokens private.

**Review gate:** the user can open one URL and complete the actual judged flow.
The release states exactly whether actions were simulator or Razorpay Test Mode,
which model ran, which tests executed, and what remains outside merchant production.

## Requirement coverage and completion ledger

| Requirement | Owning task(s) | Evidence location |
|---|---|---|
| F01 n8n fresh-volume/recovery | CP01 | `docs/validation/t153-fresh-volume-n8n.md` |
| F02 Temporal retirement | CP02, CP06 | `docs/validation/t154-temporal-drain.md` |
| F03 hosted composition | CP03, CP05 | Hosted runtime and real OIDC test results |
| F04 full durable lifecycle | CP06, CP07, CP11 | Hosted scenario/action/audit records |
| F05 fresh advisory agent | CP06 | Boundary tests and recorded provider calls |
| F06 specialist round 2 | CP08 | Versioned source/split/training/evaluation manifests |
| F07 private secrets API | CP04, CP09 | Mutual-TLS/access/network/rotation tests |
| F08 no credential exposure | CP04, CP05, CP09, CP11 | Git/image/browser/log canary checks |
| F09 OIDC and tenant roles | CP05, CP11 | Login/expiry/tenant/approval browser and API evidence |
| F10 data durability | CP03, CP10 | Migrations, integrity and isolated restore evidence |
| F11 reproducible Render | CP09 | Blueprint validation, inventory and deployed revision |
| F12 observability/provenance | CP08, CP10 | Trace, dashboard, graph, MLflow/Langfuse/audit links |
| F13 final demo | CP11 | Hosted release report and judge script |

No CP task is marked complete by this planning change. Existing T153/T154 and
specialist qualification statuses are unchanged. The next execution task is CP01;
CP03/CP04 design implementation and approved data preparation can proceed while
the operator finishes n8n key setup.
