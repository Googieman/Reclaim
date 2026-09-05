# T153 fresh-volume and recovery validation

Validation date: 2026-09-04 (Asia/Calcutta host; run artifacts use UTC IDs).

This record contains only observed results. It does not claim production
qualification, merchant-side effects, benchmark performance, or a completed
n8n orchestration run.

## Scope and safety

- T153 used uniquely prefixed Compose projects only. The final harness-prepared
  project was `reclaim-t153-20260904i`.
- The existing `reclaim-demo` project and its volumes were not torn down or
  recreated. Temporal services and artifacts were not removed or modified.
- API live actions, live financial actions, and remote side effects remained
  disabled. Raw narrative, API keys, service tokens, MinIO secrets, and Kafka
  credential data are omitted from this document and the recorded evidence.

## Commands and observed results

Static and focused checks:

```text
python -m pytest tests/unit/test_t153_validation_harness.py tests/unit/test_t153_playwright_contract.py tests/unit/test_t153_restart_recovery_contract.py tests/unit/test_t153_acceptance_contract.py -q
41 passed in 3.13s

python -m ruff check tests/support/t153_runtime.py tests/acceptance/test_t153_n8n_runtime.py tests/acceptance/test_t153_restart_recovery.py tests/acceptance/conftest.py tests/acceptance/test_intake_to_timeline.py tests/unit/test_t153_*.py
All checks passed!
```

The plan's selected backend gate passed with `70 passed in 15.28s`. Frontend
regressions passed: typecheck, lint, Vitest (`11 passed`), and production build
with routes `/cases` and `/cases/[caseId]`.

The final fresh preparation used source-built API/web images, explicit isolated
T153 networks, and loopback ports. It completed with:

```text
.\scripts\validate-t153.ps1 -Prepare -ProjectName reclaim-t153-20260904i
state=awaiting_n8n_operator_setup
Prepared T153 project=reclaim-t153-20260904i ... state=awaiting_n8n_operator_setup
```

The preserved Prepare artifacts are under
`tmp/t153/20260903T235853Z-906943/`. They record successful source builds,
healthy/running required services, a fresh project-owned PostgreSQL volume,
and sanitized Compose/image/host metadata. A direct read-only PostgreSQL
check observed one canonical tenant and an `n8n` schema and role both owned by
`n8n`. The service bindings observed for the final project were web `13800`,
API `18800`, PostgreSQL `15520`, MinIO `19800`, Redpanda `19892`, and n8n
`16300`, all on loopback.

The live backend health test passed after the Compose status parser was made
compatible with the host's newline-delimited `docker compose ps --format json`
output:

```text
python -m pytest tests/acceptance/test_t153_n8n_runtime.py::test_t153_fresh_schema_health_and_safe_runtime -q
1 passed in 2.62s
```

The real browser intake test ran without route interception against the
source-built UI and passed on both configured projects:

```text
npx playwright test -c playwright.t153.config.ts -g "accepts a unique incident"
2 passed in 30.2s
```

The full real browser suite was also run against a seeded isolated stack. It
observed one passing inbox acceptance and five failures because n8n workflows
were not active; the submitted cases remained `Not started` rather than being
treated as terminal success. This is an honest failure of the orchestration
gate, not a browser or API success claim.

The harness was then run without an operator API key:

```text
pwsh -NoProfile -File scripts/validate-t153.ps1 -Run -ProjectName reclaim-t153-20260904i
awaiting_n8n_operator_setup: complete the documented n8n owner/API-key setup before -Run.
```

The project and volumes were preserved. No n8n bootstrap, duplicate-delivery,
model-unavailable, worker/API/Redis recovery, or terminal browser scenario was
claimed after this fail-closed result.

The operator then supplied all required process values and resumed the preserved
project with PowerShell 7. Docker returned success for the PostgreSQL volume
inspection, but the harness failed before bootstrap with:

```text
PostgreSQL volume proof did not identify the expected project-named volume.
```

Read-only Docker inspection confirmed that `reclaim-t153-20260904i_postgres-data`
exists and is labeled for `reclaim-t153-20260904i`. The failure was in the
harness: it parsed redacted command output, and the local MinIO access value
overlapped the project-name text. The harness now parses the raw command result
only in memory and continues to persist sanitized evidence. The focused T153
contract matrix passes with `43 passed`.

A further resumed attempt passed Docker volume proof and the container health
check, with the API and n8n health endpoints responding successfully, but n8n
workflow bootstrap/activation exited with code 1. That attempt also exposed
that the earlier sanitized project record had redacted its project and run
directory fields, making the bootstrap artifact path unreliable. The harness
now persists the structured control-plane record without redacting paths and
reconstructs the canonical run directory from its validated run ID. The live
T153 gate remains to be rerun after this fix.

The resulting sanitized bootstrap artifact then identified the next root cause:
the pinned n8n `1.121.0` instance returned `GET method not allowed` for
`/api/v1/credentials`. Its OpenAPI document exposes credential creation but not
credential listing/update. The bootstrap now discovers managed credential IDs
from existing workflow references and creates them only when no valid reference
exists; the n8n workflow/security contract checks pass with `17 passed`. The
live gate remains to be rerun after this compatibility fix.

The next resumed attempt reached Kafka credential creation but n8n rejected the
legacy payload because `brokers` was an array and unauthenticated mode was not
explicit. The pinned Kafka credential definition requires a comma-separated
broker string and an explicit `authentication=false`. Bootstrap now normalizes
the legacy array form; the focused n8n contract matrix passes with `18 passed`.
The live gate remains to be rerun.

The next resumed attempt passed Kafka credential creation and reached workflow
creation, where n8n rejected export-only fields under its strict public write
schema. The bootstrap now allowlists writable workflow fields, omits read-only
string tags, and posts activation without an undeclared body. The combined T153
harness, n8n security, and workflow-artifact checks pass with `47 passed`.

The subsequent resumed attempt successfully upserted both workflows but failed
during handoff activation with `Consumer groupId must be a non-empty string`.
Inspection of the pinned `n8n-nodes-base.kafkaTrigger` implementation confirmed
that n8n `1.121.0` requires `parameters.topic` and `parameters.groupId`, while
the checked-in workflow used the obsolete `topics` and `consumerGroupId` fields.
The workflow now supplies the exact required fields, guarded by a regression
test. The preserved live project requires one operator-process rerun because the
API key remains intentionally unavailable outside that PowerShell process.

The first complete backend gate then proved that Kafka trigger executions were
being created successfully but ended at the initial event-type filter. The
pinned Kafka Trigger emits an unparsed broker value as `$json.message` by
default; the handoff nodes intentionally consume the authoritative envelope at
top-level `$json`. The trigger now enables `jsonParseMessage=true` and
`onlyMessage=true`, which preserves the expected typed envelope without adding
an untrusted transformation step. The live gate remains to be rerun from the
operator process that owns the API key.

## Remaining setup and gate state

T153 remains open. To resume, an operator must open the final isolated n8n URL
`http://127.0.0.1:16300`, create the local validation owner, create an n8n API
key in the n8n UI, and keep that key only in the current process environment.
The operator must also provide the Redpanda credential JSON for the internal
`redpanda:9092` connection and the matching isolated n8n service token only in
that process. Nothing should be written to tracked files or evidence.

After that setup, rerun `-Run` for the preserved project with the required
endpoint/database/MinIO environment values. The run must pass the acceptance,
duplicate-delivery, model-unavailability, worker/API/Redis recovery, and real
desktop/mobile browser gates before T153 can be checked off. No latency,
throughput, or failure-rate metric was measured because the required
orchestration run did not execute.
