# T153 Fresh-Volume and Recovery Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qualify the n8n-backed incident-intake slice on an isolated fresh Docker volume set, prove duplicate and restart recovery behavior across PostgreSQL, MinIO, Redpanda, Redis, the API, and the n8n worker, exercise the real UI against that stack, and record only observed results before marking T153 complete.

**Architecture:** Keep PostgreSQL authoritative and the transactional outbox as the only source of broker events. Add a small tenant-scoped event-relay process that publishes acknowledged outbox rows to Redpanda; n8n consumes those events and calls only the existing typed RECLAIM APIs. Use a T153-only Compose overlay and an explicitly prefixed project name for host ports, fresh volumes, n8n operator bootstrap, fault injection, and evidence capture. Redis remains n8n queue coordination, MinIO remains immutable narrative storage, and Temporal remains untouched and drain-only.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, aiokafka, MinIO SDK, PostgreSQL 16, Redpanda 24.3, Redis 7.4, n8n 1.121 queue mode, Docker Compose, PowerShell 7, pytest, Next.js 16, React 19, TypeScript, Playwright.

**Spec:** `specs/001-incident-intake-containment/spec.md` FR-026–FR-032 and SC-002/SC-003/SC-007/SC-008/SC-010; `specs/001-incident-intake-containment/plan.md`; `specs/001-incident-intake-containment/quickstart.md`; `specs/001-incident-intake-containment/decisions/ADR-004-n8n-orchestration-boundary.md`; task T153 in `specs/001-incident-intake-containment/tasks.md`.

## Global Constraints

- PostgreSQL is authoritative for cases, incidents, outbox watermarks, orchestration runs, stage attempts, and audit records. n8n execution history and Redis contents are never accepted as business truth.
- n8n may have only its isolated n8n-schema database credential, queue credential, read-only Kafka credential, and the tenant-scoped orchestrator API token. It receives no RECLAIM PostgreSQL, MinIO, model-provider, approval, or Action Gateway credential.
- The event relay may read/update only PostgreSQL outbox state for the configured tenant and publish to the domain topic. It is not an orchestrator and performs no business side effect.
- Narrative bytes stay in immutable MinIO. Redpanda payloads, n8n saved execution data, logs, summaries, and committed evidence must contain metadata/checksums only.
- Keep `RECLAIM_LIVE_ACTIONS_ENABLED=false` and `RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED=false` in every T153 service and assertion. The validation must report zero remote side effects.
- Use a unique project name matching `^reclaim-t153-[a-z0-9-]+$`. Never remove or recreate the existing `reclaim-demo` project or its volumes. Preserve T153 volumes and raw logs after a failure unless the operator explicitly supplies `-Cleanup`.
- The worktree is broadly dirty. Preserve all unrelated edits, stage no broad path, and do not create commits in this execution unless the user separately authorizes commits. At each task boundary, inspect only the listed paths with `git diff -- <paths>`.
- T154 is out of scope. Do not remove Temporal dependencies or services, do not start new work on Temporal, and leave T154 unchecked.
- Latency and recovery thresholds are provisional. Record observed sample size, p50/p95, throughput, recovery time, failures, host resources, image IDs, and limitations; never convert a target into a measured claim.

## Qualification Matrix

| Scenario | Fault timing | Required PostgreSQL result | Required transport/orchestrator result | UI/result |
|---|---|---|---|---|
| Fresh happy path | New project and named volumes | One incident, case, outbox row, run, and each stage attempt | Outbox is broker-acknowledged; one owning n8n execution reaches `awaiting_human` or an explicit `requires_attention` | New row highlights, then detail opens |
| Intake duplicate | Same idempotency key and body twice | Original incident/case IDs; no second case/outbox/business row | No second owning run or stage set | Existing case remains the single row |
| Broker duplicate | Republish the exact authoritative envelope | One run and at most one attempt per stage/idempotency key | Second n8n execution loses the owner gate before model/stage work | Terminal state remains unchanged |
| n8n worker restart | Queue work while worker is stopped, then restart it | Accepted case and outbox remain durable | Queued job resumes and reaches an explicit terminal orchestration status | Polling stops at terminal status |
| API restart | Worker starts while API is briefly unavailable, then API returns within bounded retry policy | No duplicate run/stage rows | HTTP node retries recover; otherwise one explicit `requires_attention` is persisted after API returns | No fabricated success |
| Redis restart | Restart Redis with a queued job and AOF enabled | Case/outbox/run truth is unchanged in PostgreSQL | Queue resumes from persisted coordination data; no duplicate owner/stages | Case remains visible throughout |
| Model unavailable | Provider unavailable in the safe default profile | One run ends `requires_attention` with `model_unavailable` | No replay substitution and no human-handoff success record | Failure code is visible on inbox/detail |

---

### Task 1: Make fresh PostgreSQL initialization and isolated host ports deterministic

**Files:**
- Create: `infra/postgres/010-apply-reclaim-migrations.sh`
- Modify: `infra/docker-compose.yml`
- Modify: `tests/integration/test_source_built_deployment.py`
- Modify: `tests/integration/test_compose_topology.py`

**Interfaces:**
- PostgreSQL mounts `backend/db/migrations` at `/reclaim-migrations:ro`, not over `/docker-entrypoint-initdb.d`.
- `/docker-entrypoint-initdb.d/010-apply-reclaim-migrations.sh` applies every `/reclaim-migrations/*.sql` in lexical order with `ON_ERROR_STOP=1`; the existing `900-n8n-role.sql` and `901-n8n-role-password.sh` remain later init entries.
- API and web host ports become `${RECLAIM_API_PORT:-8000}` and `${RECLAIM_WEB_PORT:-3000}` while container ports remain 8000 and 3000.

- [ ] **Step 1: Add failing static deployment tests.** Parse Compose volume short syntax into source/target pairs. Assert no mount target equals `/docker-entrypoint-initdb.d`, the migration source targets `/reclaim-migrations`, the dispatcher targets `/docker-entrypoint-initdb.d/010-apply-reclaim-migrations.sh`, role files retain the `900`/`901` targets, and API/web port strings contain the new host-port variables. Add `event-relay`, `n8n-main`, and `n8n-worker` to the topology service inventory now so Task 2 starts red.

```python
postgres_targets = {mount.split(":", 2)[1] for mount in services["postgres"]["volumes"]}
assert "/docker-entrypoint-initdb.d" not in postgres_targets
assert "/reclaim-migrations" in postgres_targets
assert "/docker-entrypoint-initdb.d/010-apply-reclaim-migrations.sh" in postgres_targets
assert "${RECLAIM_API_PORT:-8000}:8000" in services["api"]["ports"][0]
assert "${RECLAIM_WEB_PORT:-3000}:3000" in services["web"]["ports"][0]
```

- [ ] **Step 2: Run the deployment tests and verify the intended failures.**

Run: `python -m pytest tests/integration/test_source_built_deployment.py tests/integration/test_compose_topology.py -q`

Expected: FAIL on the nested init-directory mount, absent port variables, and absent `event-relay` service; existing safe-default assertions continue to pass.

- [ ] **Step 3: Add the migration dispatcher and change the mounts.** The script must be POSIX `sh`, fail on the first migration error, quote filenames, and let the official PostgreSQL entrypoint supply `POSTGRES_USER` and `POSTGRES_DB`.

```sh
#!/bin/sh
set -eu

for migration in /reclaim-migrations/*.sql; do
  [ -f "$migration" ] || continue
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$migration"
done
```

- [ ] **Step 4: Parameterize only the host-side API/web ports.** Keep the internal URLs `http://api:8000` and `http://web:3000` unchanged so same-origin routing and service discovery do not vary with the validation overlay.

- [ ] **Step 5: Validate rendered Compose configuration.**

Run: `docker compose -f infra/docker-compose.yml config --quiet`; `docker compose -f infra/docker-compose.yml --profile full config --services`

Expected: both commands exit 0; the service list includes PostgreSQL, Redpanda, Redis, MinIO, API, web, n8n main/worker, and—after Task 2—`event-relay`.

- [ ] **Step 6: Re-run the static tests.** The only remaining expected failure at this point is the deliberately predeclared `event-relay` inventory assertion, which Task 2 closes.

### Task 2: Add the missing PostgreSQL-outbox-to-Redpanda runtime relay

**Files:**
- Create: `backend/app/events/outbox_relay.py`
- Create: `tests/unit/test_outbox_relay.py`
- Modify: `backend/app/config.py`
- Modify: `backend/Dockerfile`
- Modify: `infra/docker-compose.yml`
- Modify: `scripts/start-demo.ps1`
- Modify: `scripts/status-demo.ps1`
- Modify: `scripts/stop-demo.ps1`
- Modify: `tests/integration/test_source_built_deployment.py`
- Modify: `tests/integration/test_compose_topology.py`

**Interfaces:**
- `python -m app.events.outbox_relay` starts one `AIOKafkaProducer`, polls the configured tenant's PostgreSQL outbox through `RedpandaOutboxPublisher`, watermarks only acknowledged rows, backs off after transport/database errors, and stops cleanly on SIGINT/SIGTERM.
- The relay authorization context is `IdentityType.SERVICE`, subject `reclaim-event-relay`, role `service`, and the configured `RECLAIM_TENANT_ID`.
- Configuration adds bounded `outbox_batch_size` (1–1000), `outbox_poll_interval_seconds`, and `outbox_error_backoff_seconds` settings with safe defaults.
- Compose service `event-relay` uses the API image/build, has only PostgreSQL/Redpanda/tenant settings, joins only `data-services`, and depends on healthy PostgreSQL and Redpanda. It receives no n8n, MinIO, model, approval, or Action Gateway credential.

- [ ] **Step 1: Write failing relay-loop unit tests.** Inject fake producer, publisher, connection/UoW factory, clock/sleep, and stop event. Prove one producer lifecycle per process, acknowledged publication, idle polling, bounded retry after a raised transport error, and clean shutdown. Assert the constructed service context is tenant-bound and allowlisted.

```python
async def test_relay_retries_without_watermarking_a_failed_publish() -> None:
    stop = StopAfterSleeps(1)
    publisher = StubPublisher([RuntimeError("broker unavailable"), ()])

    await run_relay(
        settings=relay_settings(),
        publisher=publisher,
        unit_of_work_factory=fake_uow_factory,
        sleep=stop.sleep,
        should_stop=stop,
    )

    assert publisher.calls == 2
    assert stop.delays == [relay_settings().outbox_error_backoff_seconds]
```

- [ ] **Step 2: Run the new tests and verify import/entrypoint failures.**

Run: `python -m pytest tests/unit/test_outbox_relay.py -q`

Expected: FAIL because `app.events.outbox_relay` does not exist.

- [ ] **Step 3: Implement the smallest relay runner around the existing publisher.** Reuse `RedpandaOutboxPublisher`; do not duplicate serialization, authority checks, outbox queries, or watermark logic. Log counts/event IDs only—never event payloads or narrative. Close the producer in `finally`.

```python
context = TenantAuthorizationContext(
    subject="reclaim-event-relay",
    tenant_id=settings.tenant_id,
    roles=frozenset({"service"}),
    identity_type=IdentityType.SERVICE,
    issuer="local-runtime",
)
```

- [ ] **Step 4: Make the source-built image runnable as both API and relay.** Add the already pinned `aiokafka==0.12.0` to `backend/Dockerfile`; retain the API `CMD` and override only `command` in Compose. Extend the Dockerfile assertion to require both `aiokafka==0.12.0` and `minio==7.2.12`.

- [ ] **Step 5: Add `event-relay` to full-profile lifecycle scripts.** `start-demo.ps1` waits for the relay process to be running; `status-demo.ps1` lists it; `stop-demo.ps1` stops it without `down -v` or volume deletion.

- [ ] **Step 6: Run relay and deployment tests.**

Run: `python -m pytest tests/unit/test_outbox_relay.py tests/integration/test_redpanda_delivery.py tests/integration/test_source_built_deployment.py tests/integration/test_compose_topology.py -q`

Expected: PASS, including broker-ack-before-watermark behavior and credential-boundary assertions.

### Task 3: Make n8n bootstrap, retries, and model-unavailable recovery executable

**Files:**
- Modify: `infra/n8n/bootstrap.ps1`
- Modify: `infra/n8n/workflows/incident-analysis-handoff.v1.json`
- Modify: `infra/n8n/workflows/incident-analysis-error-recovery.v1.json`
- Modify: `infra/n8n/README.md`
- Modify: `tests/integration/test_n8n_workflow_artifacts.py`
- Modify: `tests/security/test_n8n_orchestrator_identity.py`

**Interfaces:**
- `bootstrap.ps1` adds `-Activate` and remains idempotent. Activation is rejected unless `N8N_API_KEY`, `N8N_KAFKA_CREDENTIAL_DATA_JSON`, and `RECLAIM_N8N_SERVICE_TOKEN` are present.
- Bootstrap upserts credentials, imports/updates the recovery workflow first, replaces the handoff workflow's symbolic `settings.errorWorkflow` value with the returned recovery workflow ID, then activates and re-reads the handoff workflow to verify `active=true` when `-Activate` is supplied.
- All RECLAIM HTTP nodes use bounded n8n retry settings. A typed agent result with `status=unavailable` records `requires_attention` and `failure_code=model_unavailable`; it does not record a completed analyze/human-handoff stage and does not substitute replay.
- A duplicate Kafka delivery that receives another execution's authoritative run exits through the false output of `Execution owns run` before normalization, model analysis, or stage callbacks.

- [ ] **Step 1: Extend static workflow tests first.** Assert each HTTP node has `retryOnFail=true`, a finite retry count, and a finite wait; the analysis result has explicit completed/non-completed branches; the unavailable branch calls `/orchestration/recovery` with `model_unavailable`; the success branch alone reaches `Record analysis and policy` and `Record human handoff`; and the owner-gate false output is empty.

- [ ] **Step 2: Add bootstrap contract tests.** Inspect the PowerShell source to require `-Activate`, fail-closed checks for all three activation inputs, two-pass recovery/handoff upsert, replacement of `settings.errorWorkflow` with the recovery ID, an activation API call, and a post-activation verification read. Assert neither workflow JSON nor script contains a literal API key, database password, MinIO key, provider key, approval credential, or Action Gateway credential.

- [ ] **Step 3: Run the workflow/security tests and verify the intended failures.**

Run: `python -m pytest tests/integration/test_n8n_workflow_artifacts.py tests/security/test_n8n_orchestrator_identity.py -q`

Expected: FAIL on missing retry/unavailable branches and missing activation behavior.

- [ ] **Step 4: Update the handoff workflow.** Keep the current start-run owner gate. Add `Analysis completed?` immediately after `Typed AI analysis`; route exact `completed` to analyze/handoff, and route every non-completed typed status to a `Record requires_attention` API node. Use `model_unavailable` only for `unavailable`; use `policy_failed` for rejected/failed typed outcomes. Preserve typed `expected_state`, execution ID, run ID, and event-derived idempotency keys.

- [ ] **Step 5: Add bounded retries.** Apply the same finite retry policy to start, claim, normalize, stage, analysis, and recovery HTTP nodes. The acceptance test will measure actual recovery; the documentation must state the configured count/wait rather than promise an unmeasured recovery objective.

- [ ] **Step 6: Make bootstrap two-pass and verifiable.** Never emit credential data in `Write-Host`, exception details, or evidence output. Return a non-zero exit when activation prerequisites are missing or the API re-read does not report the handoff active.

- [ ] **Step 7: Run focused tests and JSON parsing.**

Run: `python -m pytest tests/integration/test_n8n_workflow_artifacts.py tests/security/test_n8n_orchestrator_identity.py -q`; `Get-Content infra/n8n/workflows/incident-analysis-handoff.v1.json -Raw | ConvertFrom-Json | Out-Null`; `Get-Content infra/n8n/workflows/incident-analysis-error-recovery.v1.json -Raw | ConvertFrom-Json | Out-Null`

Expected: all tests pass and both workflow files parse without output.

### Task 4: Add an isolated T153 Compose overlay and safe two-phase validation harness

**Files:**
- Create: `infra/docker-compose.t153.yml`
- Create: `scripts/validate-t153.ps1`
- Create: `tests/unit/test_t153_validation_harness.py`
- Modify: `.gitignore`
- Modify: `infra/.env.example`

**Interfaces:**
- The overlay exposes only loopback validation ports: web `${RECLAIM_WEB_PORT:-13000}`, API `${RECLAIM_API_PORT:-18000}`, PostgreSQL `${RECLAIM_POSTGRES_PORT:-15432}`, MinIO `${RECLAIM_MINIO_PORT:-19000}`, Redpanda `${RECLAIM_REDPANDA_PORT:-19092}`, and n8n `${RECLAIM_N8N_PORT:-15678}`.
- Redpanda advertises both `internal://redpanda:9092` and `external://127.0.0.1:${RECLAIM_REDPANDA_PORT}`; internal consumers continue to use `redpanda:9092`.
- Redis enables append-only persistence for n8n queue recovery but remains explicitly non-authoritative.
- `validate-t153.ps1 -Prepare -ProjectName <safe-name>` creates a new project, builds source images, starts the exact T153 services, waits for health, and records environment/config/image metadata under `tmp/t153/<run-id>/`.
- `validate-t153.ps1 -Run -ProjectName <same-name>` requires the existing fresh project, uses environment-only n8n secrets, bootstraps/activates workflows, runs backend and live Playwright gates, and writes a sanitized machine summary.
- `validate-t153.ps1 -Cleanup` is the only mode allowed to call `docker compose down --volumes`; it first rejects any project name that does not match `^reclaim-t153-[a-z0-9-]+$` and prints the exact Compose project and named volumes being removed.

- [ ] **Step 1: Write harness source-contract tests.** Assert loopback-only mappings, unique configurable ports, safe project-name validation before any destructive command, no default cleanup, failure preservation, environment-only secret inputs, exact service inventory, and safe action flags.

- [ ] **Step 2: Run the harness tests and verify missing-file failures.**

Run: `python -m pytest tests/unit/test_t153_validation_harness.py -q`

Expected: FAIL because the overlay and harness do not exist.

- [ ] **Step 3: Implement the T153 overlay.** Include `postgres`, `redpanda`, `redis`, `minio`, `api`, `web`, `event-relay`, `n8n-main`, and `n8n-worker`; do not include `workflow-worker` or start the `legacy-temporal` profile. Mount no host secret file.

- [ ] **Step 4: Implement `-Prepare`.** Generate a run ID from UTC time plus a short random suffix when not supplied, set `COMPOSE_PROJECT_NAME` to the validated project name, render the merged config, start with `--build --wait`, and prove the PostgreSQL volume was created by this project. If n8n has no owner/API key on the fresh volume, print the loopback n8n URL and stop successfully at an explicit `awaiting_n8n_operator_setup` phase; do not invent or scrape an API key.

- [ ] **Step 5: Implement `-Run`.** Require `N8N_API_KEY`, `N8N_KAFKA_CREDENTIAL_DATA_JSON`, and `RECLAIM_N8N_SERVICE_TOKEN` in the process environment; call `bootstrap.ps1 -Activate`; export only non-secret endpoint variables to pytest/Playwright; and redact bearer values, API keys, Kafka credential JSON, and MinIO secret values from persisted command output.

- [ ] **Step 6: Capture reproducibility metadata.** Save Docker Engine/Compose versions, host CPU/memory, git commit plus dirty-path list, merged Compose config with secrets replaced by `[REDACTED]`, image IDs/digests, UTC timestamps, project name, test exit codes, and container health. Raw artifacts remain ignored under `tmp/`; only Task 8's reviewed summary is committed documentation.

- [ ] **Step 7: Run the harness tests and Compose validation.**

Run: `python -m pytest tests/unit/test_t153_validation_harness.py -q`; `docker compose -f infra/docker-compose.yml -f infra/docker-compose.t153.yml --profile full config --quiet`

Expected: PASS with no secret literals in test output and valid merged Compose.

### Task 5: Implement live fresh-volume, duplicate-delivery, and authority acceptance tests

**Files:**
- Create: `tests/acceptance/test_t153_n8n_runtime.py`
- Create: `tests/support/t153_runtime.py`
- Modify: `tests/acceptance/conftest.py`
- Modify: `scripts/validate-t153.ps1`

**Interfaces:**
- Tests require `RECLAIM_T153_API_BASE_URL`, `RECLAIM_T153_WEB_BASE_URL`, `RECLAIM_DATABASE_URL`, `RECLAIM_REDPANDA_BROKERS`, `RECLAIM_MINIO_ENDPOINT`, and `RECLAIM_T153_PROJECT_NAME`; they skip outside the explicit T153 harness.
- A unique test marker is used as the intake idempotency key and identifier, never as narrative in logs.
- Direct SQL assertions run with `SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'` and verify exact counts in `incidents`, `cases`, `outbox_events`, `orchestration_runs`, and `orchestration_stage_attempts`.
- The MinIO assertion parses the persisted raw reference, downloads the one object, and verifies its stored SHA-256 metadata/checksum without printing content.
- Broker-duplicate injection republishes the exact serialized authoritative outbox envelope; it never fabricates a different checksum or event identity.

- [ ] **Step 1: Write the fresh-schema and health test.** Assert migration objects/constraints/RLS exist, the n8n schema owner is `n8n`, every required container is healthy/running, `/health/ready` reports `mode=live` with both action flags false, `/cases` returns 200 through same-origin web routing, and Temporal is absent from the T153 project.

- [ ] **Step 2: Write the accepted-intake test.** POST a complete typed request with `Authorization: Bearer demo-reviewer`, paired integer amount/currency, and unique identifier. Poll PostgreSQL until the relay watermark appears, then poll the case API only while status is `queued`/`running`. Require terminal `awaiting_human` for an available validated model or `requires_attention` with an allowlisted failure code for the default unavailable model; never accept a silent replay result.

```python
payload = {
    "tenant_id": TENANT_ID,
    "correlation_id": marker,
    "source": "merchant_portal",
    "received_at": occurred_at,
    "incident_type": "unauthorized_payment",
    "occurred_at": occurred_at,
    "narrative": "T153 synthetic operator report; validation data only.",
    "payment_reference": marker,
    "reported_amount_minor": 12345,
    "reported_currency": "INR",
    "external_reference": marker,
    "reporter_context": {"validation": "t153"},
    "idempotency_key": marker,
}
```

- [ ] **Step 3: Assert all durable stores.** Require one incident, one case, one `incident.accepted` outbox row, non-null `published_at`, one matching MinIO object/checksum, one intake audit record, one initial timeline event, one orchestration run, and at most one attempt for each `(run_id, stage, idempotency_key)`. Parse the broker envelope and assert the narrative string and raw bytes are absent.

- [ ] **Step 4: Write the intake duplicate test.** Submit the identical request again and require `status=duplicate`, the same incident/case IDs, one business row set, one accepted-event outbox row, one owning orchestration run, and unchanged stage-attempt counts.

- [ ] **Step 5: Write the broker duplicate test.** Republish the exact authoritative event and wait for a second n8n execution to appear operationally. Require the PostgreSQL owner run ID/external execution ID to remain unchanged and no additional model audit or stage attempts. Treat inability to inspect n8n execution count as an evidence limitation, not permission to infer it.

- [ ] **Step 6: Run this acceptance file only through the prepared stack.**

Run: `.\scripts\validate-t153.ps1 -Run -ProjectName reclaim-t153-20260904`

Expected: the fresh/duplicate acceptance group passes; summary reports exact row/object/execution counts and zero remote side effects. If operator n8n setup is incomplete, the harness exits with the documented setup phase and does not mark the group passed.

### Task 6: Implement the worker/API/Redis restart-recovery matrix

**Files:**
- Create: `tests/acceptance/test_t153_restart_recovery.py`
- Modify: `tests/support/t153_runtime.py`
- Modify: `scripts/validate-t153.ps1`

**Interfaces:**
- Restart helpers accept only the validated T153 project and an enum of `n8n-worker`, `api`, or `redis`; arbitrary service names and arbitrary Compose projects are rejected.
- Every scenario records pre-fault and post-recovery PostgreSQL snapshots plus monotonic elapsed recovery time.
- A scenario passes only when the case reaches `awaiting_human` or explicit `requires_attention`, PostgreSQL counts remain idempotent, MinIO stays readable, and both live-action flags/remote side-effect count remain zero.

- [ ] **Step 1: Write safe restart-helper tests.** Verify command construction uses `docker compose -p <validated-name> -f <base> -f <overlay>`, rejects `reclaim-demo`, rejects services outside the enum, and never uses `down`, `rm`, or volume deletion during a recovery scenario.

- [ ] **Step 2: Implement worker recovery.** Stop `n8n-worker`, submit a unique intake, wait for the outbox watermark and queued n8n work, start the worker, and require terminal orchestration. Assert exactly one run and no duplicate stage key.

- [ ] **Step 3: Implement API recovery.** Stop the worker, submit intake, wait for broker publication/queued work, stop API, start the worker so the claim hits the bounded retry policy, restart API within that retry window, and require terminal orchestration. If retries exhaust, require a single persisted `requires_attention` after API restoration; never accept a stuck `running` record as recovery.

- [ ] **Step 4: Implement Redis recovery.** Stop the worker, submit intake, prove a queue job exists without persisting its body, restart Redis, prove Redis health and AOF reload, start the worker, and require terminal orchestration. Compare authoritative PostgreSQL snapshots before/after Redis restart to prove no case/outbox/run truth moved into Redis.

- [ ] **Step 5: Add an already-terminal control.** Restart all three allowed services after a completed case and assert its run ID, stage, status, failure code, MinIO checksum, and stage-attempt counts do not change.

- [ ] **Step 6: Run restart tests twice.**

Run: `python -m pytest tests/acceptance/test_t153_restart_recovery.py -q` twice against the same prepared T153 stack with unique markers.

Expected: both runs pass independently; no scenario leaves `queued`/`running` beyond its timeout; no duplicate run/stage/business rows or remote side effects appear.

### Task 7: Run Playwright against the real Compose UI with no route mocks

**Files:**
- Create: `frontend/playwright.t153.config.ts`
- Create: `frontend/src/components/cases/CaseInbox.live.browser.spec.ts`
- Create: `frontend/src/app/cases/[caseId]/CaseDetail.live.browser.spec.ts`
- Modify: `frontend/package.json`
- Modify: `scripts/validate-t153.ps1`

**Interfaces:**
- `npm run test:browser:t153` uses `RECLAIM_T153_WEB_BASE_URL`, sets no `webServer`, and fails if the variable is absent. It does not start/reuse a development server.
- Live specs contain no `page.route`, `route.fulfill`, mocked payload, or replay fixture import.
- Each browser run submits a unique incident, observes the real accepted announcement/highlight, follows the real case link, and observes the real orchestration terminal state from PostgreSQL-backed APIs.

- [ ] **Step 1: Add the dedicated Playwright config and package script.** Keep the existing mocked component config unchanged. Use desktop Chromium and mobile Chrome projects, retain trace/screenshot only on failure, and run serially to preserve deterministic intake assertions.

- [ ] **Step 2: Write the live inbox test.** Navigate to `/cases`, verify server-qualified mode/safe-action labels, open the accessible intake dialog, fill all required fields plus paired amount/currency, submit, assert the exact accepted case ID is announced and highlighted, and verify identifier search returns exactly that case. Do not inspect or assert the raw narrative in browser output.

- [ ] **Step 3: Write the live detail test.** Open the highlighted case link, assert tenant merchant name, incident type, identifiers, integer minor amount/currency, `unverified` value label, workflow version, terminal orchestration status/failure code, and absence of raw narrative. Verify no automatic approval/action execution is triggered by page load.

- [ ] **Step 4: Cover responsive and polling behavior.** On mobile, verify the intake sheet and case card are keyboard/screen-reader reachable. In the worker-recovery browser scenario, observe queued/running, restart the worker through the safe helper, then verify polling stops after `awaiting_human` or `requires_attention` rather than continuing network requests indefinitely.

- [ ] **Step 5: Run mocked and live suites separately.**

Run from `frontend/`: `npx playwright test`; `npm run test:browser:t153`

Expected: existing mocked tests pass; live desktop/mobile tests pass against the T153 base URL with no route interception.

### Task 8: Execute the full gate, sanitize evidence, and reconcile T153 status

**Files:**
- Create: `docs/validation/t153-fresh-volume-n8n.md`
- Modify: `specs/001-incident-intake-containment/quickstart.md`
- Modify: `docs/architecture/fs001-traceability.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `specs/001-incident-intake-containment/tasks.md`

**Interfaces:**
- The validation document records commands, UTC timestamps, environment, image IDs, exact pass/fail/skip counts, durable-store counts, orchestration outcomes, measured p50/p95 intake-to-terminal latency, recovery times, throughput/sample size, failure rate, zero/observed forbidden attempts and side effects, and limitations.
- T153 changes from `[ ]` to `[X]` only if every required matrix row passes on a fresh project and the live browser suite passes. A blocked or failed row leaves T153 unchecked and is recorded in both validation evidence and `PROJECT_STATUS.md`.
- T154 remains `[ ]` and Temporal artifacts remain present.

- [ ] **Step 1: Run static and focused gates before the destructive-free fresh run.**

Run: `python -m pytest tests/contract/test_incident_intake_n8n.py tests/unit/test_outbox_relay.py tests/unit/test_t153_validation_harness.py tests/integration/test_n8n_workflow_artifacts.py tests/integration/test_source_built_deployment.py tests/integration/test_compose_topology.py tests/security/test_n8n_orchestrator_identity.py -q`

Expected: all selected tests pass with no unexpected skip.

- [ ] **Step 2: Prepare one uniquely named fresh project.**

Run: `.\scripts\validate-t153.ps1 -Prepare -ProjectName reclaim-t153-20260904`

Expected: source images build; fresh named volumes initialize; required containers become healthy/running; the script either reaches `prepared` or reports the exact `awaiting_n8n_operator_setup` phase without claiming acceptance.

- [ ] **Step 3: Complete the explicit n8n operator setup when requested.** Open the loopback n8n URL, create the local validation owner/API key, export the API key, Kafka credential JSON for `redpanda:9092`, and the demo orchestrator token in the current process only. Do not save them to tracked files or paste them into evidence.

- [ ] **Step 4: Run the complete T153 gate.**

Run: `.\scripts\validate-t153.ps1 -Run -ProjectName reclaim-t153-20260904`

Expected: fresh-volume, duplicate, model-unavailable, worker/API/Redis restart, backend regression, and live desktop/mobile browser groups all pass. Any failure stops status promotion while preserving volumes/logs for diagnosis.

- [ ] **Step 5: Run repository regressions appropriate to changed boundaries.**

Run: `python -m pytest -q`; from `frontend/`: `npm test`; `npm run typecheck`; `npm run lint`; `npm run build`; `npx playwright test`

Expected: all available non-environment-gated tests pass. Report every skip and any pre-existing failure verbatim; do not hide it behind focused-suite success.

- [ ] **Step 6: Review and sanitize generated evidence.** Search the raw evidence directory and proposed Markdown for the API key, service token, MinIO secret, Kafka credential JSON, and the synthetic narrative. Replace secrets with `[REDACTED]`; omit narrative entirely. Confirm the document distinguishes target values from observations and includes the sample size.

- [ ] **Step 7: Update documentation from observed output only.** Correct the quickstart bootstrap invocation to the implemented parameters and describe the two-phase T153 run. Link actual tests/artifacts from traceability. Replace stale Docker/UI status in `PROJECT_STATUS.md` with the new dated result, including failures or qualifications.

- [ ] **Step 8: Promote or retain T153 honestly.** Mark T153 `[X]` only if Steps 1–7 meet every matrix requirement. Otherwise leave `[ ]` and list the exact failed scenario, command, and preserved project name needed to resume. In both cases, assert T154 is still `[ ]`.

- [ ] **Step 9: Perform final scope and placeholder review.**

Run: `git diff --check`; `rg -n "TODO|TBD|placeholder|REPLACE_ME|changeme" backend/app/events/outbox_relay.py infra/docker-compose.yml infra/docker-compose.t153.yml infra/n8n scripts/validate-t153.ps1 tests/acceptance/test_t153_n8n_runtime.py tests/acceptance/test_t153_restart_recovery.py frontend/playwright.t153.config.ts docs/validation/t153-fresh-volume-n8n.md`; `git diff --name-only`

Expected: `git diff --check` is clean; the placeholder scan reports only intentional checked-in n8n credential identifiers if still required by inactive templates, never a credential value; the changed-file list contains only T153 files plus pre-existing user changes.

## Completion Definition

T153 is complete only when one recorded isolated fresh-volume run proves: migrations initialize without manual SQL repair; MinIO stores one immutable report per accepted identity; the relay publishes and watermarks the metadata-only event; n8n owns the new run through typed APIs; intake and broker duplicates remain idempotent; worker/API/Redis restarts recover without loss or duplicate work; model unavailability becomes explicit `requires_attention`; the real desktop/mobile UI accepts, highlights, polls, and opens the case; live action flags and remote side effects remain zero; and the evidence report contains observed, reproducible results with limitations. T154 remains a separate, unchecked decision gate.
