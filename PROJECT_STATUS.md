# RECLAIM Project Status

Last updated: 2026-09-05

## Current objective

Complete the hosted Razorpay final-round system through the documented completion
plan, preserving authoritative state, advisory-only inference, isolated actions,
and truthful simulator/Test Mode labeling. The next runtime gate remains T153.

## Railway public-service smoke verification — 2026-09-05

Computer Use verified the existing Railway `marvelous-truth` web service at
`https://marvelous-truth-production-5c3d.up.railway.app`. The public Next.js
operator UI loaded successfully and displayed its incident workspace. The
separate `Reclaim` API service is available at
`https://reclaim-production-b5df.up.railway.app`; its readiness endpoint
reported `status: ready`, with live financial actions disabled. This is a
deployment smoke observation only and does not qualify the full hosted
final-round system or its remaining production gates.

## Hosted final-round completion planning — 2026-09-05

The user-supplied final-round chat has been reconciled with the repository in
`docs/design/hosted-final-round.md` and the CP01-CP11 implementation plan in
`docs/superpowers/plans/2026-09-05-hosted-final-round-completion.md`. It covers
T153/T154, hosted composition/OIDC, durable approval-to-terminal orchestration,
actual Razorpay Test Mode transport qualification, specialist round 2, Render,
observability/projections, recovery and the final judge walkthrough.

Proposed ADR-006 records a separate private secrets broker backed by Vault, with
mutual TLS, tenant/service-specific credential delivery and deployment-mounted
bootstrap identities. Root `secrets/` now contains only invalid example JSON and
an API-key acquisition guide. Populated files in that folder are Git-ignored;
the entire folder is excluded from Docker builds.

This remains a non-deployed completion effort: the Render Blueprint and hosted
runtime are not implemented or deployed. CP03's migration runner/role foundation
and CP04's private broker contract, client/loader, provisioning validation and
transport artifacts are now implemented locally, but have not been qualified
against hosted dependencies. No provider credentials were generated, collected
or used, and no billable resource was provisioned. T153/T154 remain open; the
current specialist remains unpromoted.
Historical test counts below have not been rerun as part of this planning change.
Planning checks: all four JSON examples parse and retain `template_only: true`;
runtime bundle/consumer references agree with the example access policy, the
agent/BFF have no broker grants, and Git ignores populated/nested secret files.

## Agent/chatbot integration slice — 2026-09-05

The dedicated integration branch reconciles the hosted runtime/model-gateway and
Railway Docker fixes into one candidate line. `backend/db/migrate.py` is the
canonical checksum-ledger runner; the older application import is a compatibility
shim. The repository disposition is recorded in
`docs/maintenance/2026-09-05-repository-reconciliation.md`.

The separate `reclaim-help-deepseek` profile is locally wired end to end through
an authenticated reviewer-only `/help/chat` route, deterministic reviewed-passage
retrieval, explicit insufficient/unavailable states, and a small accessible UI.
Case-aware help is disabled. The model manifest and private Railway-shaped service
are checked in, but no weights were downloaded, no model resource was provisioned,
and the feature remains disabled by default. Help evaluation is
`resource_blocked` with `metrics: null`; the dataset expectations are not results.

Independent investigation boundary tests cover typed advisory proposals, provider
timeout, tenant/service identity, and rejection of remote side effects. The
investigation qualification report remains `not_qualified`: no held-out merchant
set, private model resource, or T153/T154 live evidence is available. No live
connector, payment, refund, cancellation, or account mutation was performed.

Verification for this slice: full Python suite `835 passed, 51 skipped, 8
warnings`; the skips are the existing external-service/T153/T154 gates. Frontend
Vitest passes `14 tests`, typecheck, lint, and production build pass. Scoped Ruff
for the changed Python files, PowerShell preparation-script parsing, and
`git diff --check` pass. The machine used Node `v24.19.0` while the frontend
declares `>=20.18.0 <23`; the build nevertheless completed successfully, and the
engine mismatch is retained as an environment note rather than hidden.

## CP01/T153 resumed qualification check — 2026-09-05

The clean hosted-final-round worktree reran the CP01 static/contract gate:
`python -m pytest tests/unit/test_t153_acceptance_contract.py
tests/unit/test_t153_playwright_contract.py
tests/unit/test_t153_restart_recovery_contract.py
tests/unit/test_t153_validation_harness.py
tests/integration/test_n8n_workflow_artifacts.py
tests/security/test_n8n_orchestrator_identity.py -q` passed with `66 passed`.

The live gate remains blocked, not passed: the host has no preserved
`reclaim-t153-*` containers, volumes, or harness record, and no operator-owned
n8n bootstrap/API key, Kafka credential JSON, or tenant-scoped n8n service token
was available. The fail-closed resume command
`pwsh -NoProfile -File scripts/validate-t153.ps1 -Run
-ProjectName reclaim-t153-20260904i` returned exit code `1` with
`No prepared T153 project record exists`. No project or volume was created or
removed, and no credentials or external service were contacted. T153 remains
unchecked; T154 remains unchecked. A prepared project and operator-provided
bootstrap inputs are required before CP01 can produce live evidence.

## CP03/CP04 local implementation gate — 2026-09-05

The independent hosted foundation slice is implemented in the isolated worktree:

- `db.migrate` discovers numbered SQL migrations, uses a fixed PostgreSQL
  advisory transaction lock, records content checksums in an append-only ledger,
  rejects modified applied migrations, and keeps `--check` read-only.
- Migration `014_hosted_service_roles.sql` adds NOLOGIN service group roles and
  an append-only `secret_access_events` table with insert-only broker-audit
  access; it stores no secret payload or value.
- `secret_broker` exposes strict request/bundle contracts, exact identity/tenant
  and Vault-path policy, audit-before-release, bounded in-memory caching, a
  private FastAPI endpoint, and a client/runtime loader. The provisioning CLI
  rejects templates, sentinel values and path overrides and prints metadata only.
- Envoy and entrypoint artifacts require mutual TLS on `8443`, keep the broker
  application on loopback, expose only a separate boolean health listener, and
  do not publish a Docker secret port.

Focused validation: `18 passed, 3 skipped`; Ruff and Python compilation passed.
The skips are the live migration database, live broker/mTLS endpoint, and Vault
credential gates. No Vault write, provider call, deployment, or secret delivery
was performed. CP04's hosted review gate remains open until actual mTLS transport,
Vault audit/rotation/outage, and access-matrix checks pass.

## CP05 partial hosted runtime assembly — 2026-09-05

`app.runtime.HostedRuntime` and `api.main.create_hosted_app` now provide a
production-shaped dependency assembly using injected PostgreSQL, storage and
verified OIDC boundaries. Hosted readiness probes authoritative PostgreSQL with
`SELECT 1`; it does not run canonical replay or mount local-demo routes. The
fresh-agent guard permits production only when a trusted provider transport is
present and continues to reject live financial actions.

Focused validation: `11 passed` across hosted runtime, hosted identity and
fresh-agent API/profile tests. Full OIDC authorization-code/PKCE login, server-
side BFF/session storage, hosted browser tests, and real identity/tenant role
qualification remain open CP05 gates; no hosted identity or deployment was used.

## Current milestone: n8n-backed incident intake and operator inbox — 2026-09-04

The n8n ownership amendment is implemented through the typed application/API
boundary and checked-in deployment artifacts. Structured intake now persists
typed, unverified metadata in PostgreSQL, captures the narrative only in the
immutable raw-report store, emits a metadata-only `incident.accepted` event,
and exposes the tenant-scoped `/cases` inbox and case detail read models.
The versioned n8n handoff claims runs and stages through allowlisted APIs; the
authoritative PostgreSQL owner gate stops duplicate deliveries before model or
later-stage work, and the error workflow records `requires_attention`.

Observed validation for this milestone so far:

- Action/connector qualification hardening is locally verified in the deterministic
  boundary: tenant-scoped connector/action allowlists, bounded parameter/amount
  limits, emergency-disable and circuit-breaker controls, service-role checks,
  simulator-only action manifests, credential-free simulator invocation,
  authoritative-payment refund validation, malformed-response-to-UNKNOWN handling,
  and PostgreSQL lifecycle mutation guards are implemented. The focused action,
  approval, connector, recovery, verification, escalation, and containment matrix
  passes: `150 passed, 8 warnings`; the additional chaos/cross-tenant/FS hardening
  matrix passes: `46 passed, 8 warnings`. Ruff, compilation, and scoped diff checks
  pass; compilation reports only the existing `.pytest_cache` listing notice.
  This qualifies deterministic simulator/Test Mode/static safety controls only.
  Live merchant connectors, provider credentials, and live financial execution are
  not qualified and remain disabled; no real merchant system or external network
  was called.

- Phase 3 model/evaluation readiness controls are implemented in the provider-neutral
  evaluation boundary: manifest shape and lineage validation, grouped temporal split
  checks, sealed held-out/composition qualification gates, confidence-interval and
  report provenance, drift detection, strict typed-output rejection, and promotion
  gates for shared manifests, complete observations, safety, composition, drift, and
  artifact evidence. Focused Phase 3 validation passes: `9 passed`; the broader model,
  evaluation, dataset-pipeline, Soup-artifact, and model-safety subset passes:
  `29 passed, 8 warnings`; Ruff, compilation, and scoped diff checks pass.
- The checked-in training dataset remains structurally `valid` but is not qualification
  ready: it has one development case, zero validation cases, and zero held-out cases.
  The checked-in base/specialist reports remain `not_run`; promotion returns
  `DON'T SHIP` with exit code 2. The observed one-case adapter's strict serving probe
  remains schema-invalid and is not promoted. No data, performance, drift, or model
  quality claim is inferred from these artifacts.

- Python source compilation completed without syntax errors (the command also
  reported the existing non-source `.pytest_cache` listing notice).
- Backend contract, unit, and security gates pass: `385 passed, 1 skipped`.
- The focused intake, inbox, workflow-artifact, and n8n-identity gates pass:
  `27 passed` including the existing intake contract coverage.
- Frontend typechecking, Vitest, lint, and production build pass (`11` frontend
  tests; routes include `/cases` and `/cases/{caseId}`).
- The `/cases` visual direction now follows the supplied incident-console
  references: compact dark navigation rail, light queue workspace, persistent
  incident search, queue tabs, status summaries, dense incident rows, and a
  responsive full-screen intake sheet. On the source-built isolated T153
  project, real browser intake, accepted-case highlighting, identifier search,
  and the mobile card/accessibility path passed on both desktop and mobile.
- Full Compose configuration and the test overlay validate successfully; n8n
  workflow JSON and the filesystem artifact validator also pass. The validator
  reports only the intentional environment-gated open tasks T153 and T154.
- T153 focused contracts pass (`43 passed`) and targeted Ruff passes. The final
  fresh harness project `reclaim-t153-20260904i` records source-built images,
  a fresh project-owned PostgreSQL volume, one canonical tenant, an `n8n`
  schema/role owned by `n8n`, healthy required services, and loopback bindings.
  The live schema/health acceptance passes.
- Phase 0 T153 checksum validation was corrected: the immutable raw-report
  checksum and the separate narrative checksum are now validated independently,
  and the acceptance assertion checks the narrative checksum propagated into the
  authoritative event without equating it to the raw-capture checksum. The
  focused T153 suite passes (`45 passed`), scoped Ruff passes, and scoped
  `git diff --check` passes. The live-gated T153 acceptance/recovery suite was
  not run because the explicit prepared-stack environment was absent (`8 skipped`).
- The latest full available Python run is green in the project `.venv`:
  `783 passed, 49 skipped, 1 warning`. The read-only-demo acceptance regressions
  now fail closed with their stable `read-only demo` contract, and the clean
  wheel/sdist artifact smoke passes under both the project venv and system Python.
  The system-Python artifact subprocess ignores ambient environment variables
  while retaining the interpreter's installed declared runtime dependencies;
  Temporal SDK/workflow imports remain present and exercised.
- `git diff --check` passed.
- Case Inbox API synchronization now has a typed `listCases`/`getCase` gateway,
  server-qualified mode labeling, filter-clearing intake refresh/highlighting,
  stale-response-safe polling, and explicit API-versus-empty rendering. The
  authoritative local case view now projects persisted typed fresh-agent analysis
  and provenance from PostgreSQL; command panels refetch that view after fresh-agent,
  approval, simulator, and escalation requests. Fresh local regression validation
  passed: frontend Vitest `11/11`, typecheck, lint, build, targeted Ruff, and
  the authenticated localhost API smoke check. A prior isolated mocked
  Playwright run passed `11/11`; the latest default-config attempt against the
  shared localhost runtime was not promoted after `5/11` data-dependent
  failures. These are separate from the live T153 browser result below.
- The complete live T153 browser suite is not green: one inbox test passed and
  five orchestration-dependent tests failed because n8n workflows were not
  active, leaving submitted cases non-terminal. The T153 harness therefore
  stopped at `awaiting_n8n_operator_setup` and preserved the isolated project;
  it did not invent or scrape an n8n API key.
- A resumed operator run reached the preserved stack with all required process
  values present, but failed at PostgreSQL volume proof even though Docker
  reported success and the expected project-owned volume/label existed. The
  harness was parsing its own redacted JSON, which corrupted project text when
  a local MinIO credential overlapped it. The fix keeps raw command output only
  in memory for machine validation and persists sanitized evidence; the focused
  T153 contract matrix is now `43 passed`. A subsequent resumed attempt passed
  volume proof and service health but failed during n8n workflow bootstrap with
  exit code 1. The harness now preserves structured project/run paths in its
  machine record and reconstructs the canonical run directory from its
  validated run ID. The sanitized bootstrap artifact identified an n8n
  `1.121.0` compatibility issue: its public API rejects `GET /api/v1/credentials`.
  Bootstrap now discovers managed credential IDs from existing workflow
  references and creates them only when no valid reference exists; the n8n
  workflow/security contract checks pass (`17 passed`). A subsequent attempt
  reached Kafka credential creation but n8n rejected the legacy broker-array
  payload without explicit unauthenticated mode. Bootstrap now normalizes that
  input to n8n's string-broker schema with `authentication=false`; the focused
  n8n contract matrix reached `18 passed`. The next attempt passed credential
  creation and reached workflow creation, where strict public-API validation
  rejected export-only/read-only fields. Bootstrap now allowlists writable
  workflow fields and posts activation without an undeclared body; the combined
  T153 harness/security/workflow checks pass (`47 passed`). The subsequent
  activation attempt upserted both workflows but exposed a pinned n8n
  `kafkaTrigger` field mismatch: n8n `1.121.0` requires `parameters.topic` and
  `parameters.groupId`, not the obsolete `topics` and `consumerGroupId`. The
  handoff workflow and regression suite now use the exact required fields. The
  first complete backend gate showed that Kafka executions were successful but
  stopped at the event-type filter because the Kafka Trigger defaulted to a raw
  `$json.message` value. The handoff trigger now explicitly parses and emits the
  authoritative envelope with `jsonParseMessage=true` and `onlyMessage=true`.
  The live gate remains to be rerun from the operator process that owns the API
  key.

Not yet claimed: live Redpanda-to-n8n handoff, n8n workflow activation, duplicate
delivery, model-unavailability, worker/API/Redis restart recovery, terminal live
browser flow, or production credential/network qualification. T153
(fresh-volume/external/recovery/browser validation) remains intentionally open;
T154 (Temporal removal after drain qualification) remains unchecked and
unchanged. No production fraud, model-quality, latency, or financial-execution
metric is inferred. Resume details are recorded in
`docs/validation/t153-fresh-volume-n8n.md`.

### Final release-gate preflight — 2026-09-04

The deterministic read-only release gate is implemented in
`scripts/release_preflight.py` with the PowerShell entry point
`scripts/release-preflight.ps1`, and its contract is covered by
`tests/unit/test_operations_readiness.py`. It checks required artifacts, pinned
runtime metadata, production Compose security/fail-closed defaults,
deployment-input names without printing values, backup/restore controls,
health/observability artifacts, rollback guidance, and the T153/T154 gates.

Observed static preflight result: `CONDITIONAL NO-GO` with 7 repository controls
passing and 4 explicit open gates: deployment-owned release metadata,
production secret-manager inputs, T153 live fresh-volume/recovery/browser
qualification, and T154 Temporal drain/removal evidence. The command did not
start containers, call merchant/provider systems, mutate databases, or enable
live or financial actions. Production inputs and release metadata were not
available to this task, so no values were emitted and no production claim was
made.

The migration runbook now contains a fail-closed T154 checklist requiring empty
Temporal inventory, PostgreSQL/n8n parity, recovery, and fresh-volume evidence.
Temporal and its SDK/services remain present and T154 remains unchecked. The
release gate therefore does not promote T153 or authorize production release.

## Historical objective

Implement the approved FS-001 Spec Kit vertical slice from the first dependency-ordered
setup task onward:

`incident intake → evidence → Temporal workflow → bounded agent analysis → policy →
Action Gateway → verification → audit`

Application implementation has completed Phase 2 Foundation through T035: Phase 1
setup, the T009-T017 shared-contract boundary, the T018-T023 authoritative-state/audit/
event-delivery batch, and T024-T035 runtime/security boundaries are complete. The
post-T035 foundation security remediation for tenant-bound OIDC roles is complete, and
the T036-T042 US1 contract/property/integration/security test batch is complete. The
T043 canonical acceptance fixture-isolation remediation now passes against fresh live
PostgreSQL and MinIO services after the T050-T055 implementation batch. T044-T058 and
the initial remediation batch for MAJOR-1 and MAJOR-2 are
complete locally, with the revised production Temporal workflow gate and live
event-delivery/projection validation recorded below. The final US1 remediation gate
closed D1 audit-chain concurrency and D2 timeline-uncertainty handoff. D3
(MAJOR-5 authoritative provider-to-case association) was specification-approved on
2026-08-31 and its verified-correlation runtime, authoritative mapping migration,
hard-cutover resolution, quarantine, fixture, and test implementation was completed
on 2026-09-01. The D3 corrective migration and reviewer-context live-test repair
were completed on 2026-09-01; fresh live PostgreSQL/RLS validation and the requested
regression gates pass. Original Remediation Batch B for
MAJOR-2 and MAJOR-6 is complete locally. Its follow-up review kept MAJOR-7 open;
the focused approval-to-execution remediation and validation are recorded below.
T059 attribution contract coverage is complete, and test-first coverage for T060-T064
is complete. T065's canonical acceptance target now passes through the deterministic
analysis, bounded response, and typed proposal hand-off. The first US2 production
batch, T066-T069, the bounded T070-T073 model-boundary batch, and T074 are complete
for deterministic attribution/exposure hand-off, redaction, provider-neutral
replay/live analysis, read-only tools, strict response parsing, and side-effect-free
typed proposals, and deterministic proposal validation. T076-T078 now add
authoritative model-run persistence, deterministic replay fallback, and the US2
  integration gate; their implementation and second focused MAJOR-3/MAJOR-4
  remediation validation are complete. The US2 live-gate
  attempt then exposed a missing runtime grant for both migration-007 model-analysis
  tables and stopped at that blocker. Corrective migration 008 now grants the scoped
  runtime access, and fresh 001-008 plus non-owner runtime validation pass. The final
  focused MAJOR-2 identity gate now also passes live PostgreSQL qualification;
  broader live qualification remains environment-qualified; the authorized US2
  implementation through T078 is present.
Remediation Batch C is implemented for
MAJOR-8 payload enforcement,
MAJOR-9 atomic immutable evidence writes, and MAJOR-10 backend artifact discovery;
the focused Batch C checks and the clean-volume T043 remediation rerun pass. The
D3 live release gate is now closed; T059 and T060-T065 test work are complete.
The authorized US2 implementation through T078 and the US3 containment slice
through T103 are present; live financial execution remains disabled.

The US3 test-first batch T079-T087 is now present. T088-T094 are implemented as the
first US3 production slice: immutable policy/evaluation, bounded policy change
control, approval lifecycle, policy audit/outbox handoff, the isolated Action
Gateway, defensive action simulators, and the Razorpay Test Mode refund seam.
T095-T102 are implemented and locally validated in the focused slice below. T103
passed as a deterministic replay qualification; the full US3 vertical-slice gate
and safety evidence export remain locally qualified only. The US4 T104-T110
test-first batch, T111-T119 replay/evaluation implementation, T120-T124 Compose,
CI, operator UI, and mode-selection implementation, and T125 quickstart gate are
complete. T126-T130 hardening and acceptance are complete; T131-T133 are the
current final documentation/status/artifact gates.

## Historical milestone: FS-001 final acceptance and release-readiness reconciliation — 2026-09-02

T111-T113 now provide a deterministic, explicitly replay-labelled runner, canonical
mixed-activity fixture, and invalid/duplicate/order/evidence/policy/approval/
forbidden/unknown-result/verification/escalation/provider-unavailability variants.
T114-T118 provide honest benchmark provenance, leakage-safe split and post-split
overlay helpers, sealed held-out access, evaluation metrics/confidence intervals/
reports, and measured-baseline capture. T119 provides bounded redacted evaluation
traces with tenant/case/correlation propagation and non-authoritative Grafana,
Langfuse, and MLflow configuration. T120-T124 provide the declared Compose/CI
artifacts, operator UI/read models, typed UI commands, and server-authoritative
mode selection. T125-T130 provide the quickstart, hardening, and complete mixed
activity acceptance evidence. The final T131-T133 block is documentation,
status reconciliation, and artifact validation; it adds no product scope.

Verification evidence for T088-T094 is retained in the earlier record below. The
T095-T102 focused suite and the full available Python suite are recorded in the
completion entry below; live PostgreSQL, non-owner RLS, Temporal, Redpanda, and
other external-service checks remain environment-qualified and are not claimed.

## Governance approvals

- 2026-08-30: The user explicitly approved RECLAIM Constitution v1.0.0 as the
  governing constitution for this repository.
- 2026-08-30: The user explicitly approved FS-001 — Incident Intake to Verified
  Containment as the first feature boundary. The approved scope runs from incident
  and customer-compromise intake through tenant-aware evidence collection, timeline
  reconstruction, attribution and bounded agent analysis, deterministic exposure,
  typed defensive proposals, policy and approval gates, idempotent execution,
  reconciliation, verification, escalation, append-only audit, and live/replay
  demonstration support. The approved architecture remains unchanged.
- 2026-08-30: Application implementation is not authorized by these approvals; the
  Spec Kit `specify`, planning, and task-generation phases for FS-001 are complete,
  and the approved specification remains the governing feature boundary.
- 2026-08-31: The D3/MAJOR-5 contract/data-model change was approved for future
  implementation: Razorpay webhook v2.0.0 derives `VerifiedProviderCorrelation`
  v1.0.0 and resolves only through an authoritative PostgreSQL mapping. At that
  approval point, implementation remained gated.
- 2026-09-01: The user explicitly authorized and requested the D3/MAJOR-5 runtime
  remediation only, with T059 and US2 out of scope for that request.
- 2026-09-01: The user explicitly authorized T059 as the first US2 batch after the
  closed US1/D3 release gate; T059 is test-only and does not authorize T060+.
- 2026-09-01: The user explicitly authorized T060-T064 as test-only US2 work. The
  batch must not begin T065+ or add production attribution/exposure/model/proposal
  behavior; expected-red tests may target the later implementation seams.
- 2026-09-01: The user explicitly authorized T065 as test-only US2 acceptance work.
  The canonical acceptance target may remain expected-red at absent T066+ behavior;
  no T066+ production attribution, exposure, model, or proposal implementation is
  authorized in this batch.
- 2026-09-01: The user explicitly authorized the first US2 production implementation
  batch T066-T069 only: deterministic rules/LightGBM attribution, trusted exposure,
  aggregation, provenance, and uncertainty propagation. T070+ and US3 remain out of
  scope.
- 2026-09-01: The user explicitly authorized T074 only for typed model-response
  parsing, uncertainty/refusal retention, reference validation, provenance metadata,
  and side-effect-free typed proposal construction. T075+ and US3 remain out of scope.
- 2026-09-01: The user explicitly authorized T075 only for deterministic,
  side-effect-free proposal validation before policy evaluation. T076+ and US3
  remain out of scope.
- 2026-09-01: The user explicitly authorized T076-T078 only for model-analysis
  persistence, provider-unavailable deterministic replay fallback, and the US2
  integration gate. T079+ and US3 remain out of scope.
- 2026-09-01: The user explicitly authorized the grant-only repair for the confirmed
  US2 live-gate blocker: add corrective migration 008 for model-analysis runtime
  access, prove the non-owner persistence/RLS boundary, and do not start T079/US3.
- 2026-09-01: The user explicitly authorized the second focused US2 remediation
  batch for MAJOR-3 and MAJOR-4 only. MINOR-1, T079, US3, Action Gateway execution,
  financial/account side effects, attribution/exposure formulas, and
  `security-audits/` remain out of scope.
- 2026-09-01: The user explicitly authorized the US3 test-first batch T079-T087.
  T079-T086 may proceed as parallel test artifacts; T087 follows them as the
  canonical acceptance target. T088+ and all US3 production implementation remain
  out of scope for this batch.
- 2026-09-01: The user explicitly authorized implementation of US3 tasks T088-T094
  only. T095+ remains out of scope for this milestone.
- 2026-09-01: The user explicitly authorized the test-first T104-T110 batch only.
  T104 uses the existing approved replay/evaluation contracts; T105-T110 may remain
  strict expected-red tests at their exact T111-T124 owners. T111+ production work,
  shared-contract changes, constitution/ADR/AGENTS.md changes, and changes to the
  pre-existing `packages/contracts/action_gateway.py` diff are not authorized.
- 2026-09-01: The user explicitly authorized implementation of T111-T119 only:
  replay, canonical fixtures/variants, evaluation metadata and controls, measured
  baselines, and redacted observability. T120+ remains unstarted. This authorization
  does not authorize shared-contract, constitution, ADR, or migration changes; the
  pre-existing Action Gateway contract diff and US3 migration artifacts are preserved
  without modification.

## Milestone state

| Milestone | State | Evidence |
|---|---|---|
| Repository and harness audit | Complete | `.specify/`, `.agents/`, extension registry, context configuration, and git state inspected |
| Permanent agent instructions | Complete | `AGENTS.md` created with managed Spec Kit markers |
| RECLAIM constitution | Complete | `.specify/memory/constitution.md` established as v1.0.0 |
| Project status tracking | Complete | This file created; no arbitrary percentage used |
| Overall system feature specification | Approved and clarified | User approved `specs/001-incident-intake-containment/spec.md`; requirements checklist remains 16/16 |
| Clarification and implementation plan | Complete | `plan.md`, `research.md`, `data-model.md`, contracts, quickstart, and three ADRs exist |
| Task list generation and consistency analysis | Complete; implementation-ready | `tasks.md` contains 133 dependency-ordered tasks; all 25 functional requirements have traceable task coverage; requirements checklist is 16/16 |
| Application code and infrastructure | Phase 1 Setup, T009-T035 foundation, T044-T058 US1, Remediation B, MAJOR-7, Batch C, D1/D2, D3, T066-T078 US2, T079-T103 US3, and T111-T124 US4 implementation are present; T125-T130 validation artifacts are present | PostgreSQL authority/RLS, repositories/UoW, serialized tenant audit chains, outbox/inbox, Temporal, Redpanda delivery, rebuildable Neo4j projection, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, authenticated intake/webhook correlation, evidence/timeline, attribution/exposure, bounded model/proposal path, immutable policy/approval, isolated Action Gateway, reconciliation/verification/escalation, labeled replay/evaluation, Compose/CI declarations, and operator read models/UI are present |
| D3 contract/data-model/runtime | Complete; fresh live PostgreSQL/RLS gate passed | `VerifiedProviderCorrelation` v1.0.0, `ProviderCorrelationMapping`, corrective migration `006_provider_correlation_schema.sql`, hard-cutover resolver, quarantine/idempotency behavior, reviewer-context live processing, and non-owner RLS validation pass |
| US3 T088-T103 containment slice | Complete locally; live database checks unavailable | Immutable policy/evaluator and policy repositories, bounded tenant change control/API, approval lifecycle with optimistic concurrency, policy audit/outbox builders, isolated Action Gateway, defensive action manifests/simulators, Razorpay Test Mode refund seam, T095-T102 lifecycle/verification/escalation runtime, and the deterministic T103 gate are present; no live financial action is claimed |
| Foundation Security Review Gate | Passed for the tenant-role binding remediation; T036-T042 test batch complete | Scoped OIDC roles, authenticated UoW propagation, adversarial tests, Redpanda tenant binding, and local validation pass; live service checks were unavailable in this run |
| Tests and benchmark evaluations | T009-T130 test/implementation scope is complete; T131-T133 are documentation/status/artifact gates | T130 acceptance is 3 passed with one existing LangGraph deprecation warning. Final full available Python suite is 578 passed, 40 skipped, one warning; evaluation manifest has zero available cases. No benchmark, production fraud metric, or live financial claim exists |

## Quality state

- Tests: the latest repository `.venv` suite is `783 passed, 49 skipped, 1
  warning`; the focused regression matrix passed `42/42` with the same existing
  LangGraph deprecation warning. The system-Python artifact smoke also passed;
  a full system-Python suite is not treated as authoritative where optional
  dependencies are absent.
  A historical pre-US3 elevated default suite was `419 passed, 34 skipped` in the
  project `.venv`; the available run emits one LangGraph deprecation
  warning. The focused MAJOR-3/MAJOR-4 remediation suite passed `4/4`; the combined
  final T076-T078, remediation, and migration/runtime set passed `26/26` with four
  environment-dependent skips, including fresh 001-009 migration, historical-007
  upgrade, idempotent migration reapplication, and non-owner RLS validation against
  disposable PostgreSQL. The complete available US2 regression set passed `112/112`;
  the focused
  T075 adversarial suite passed `25/25`, and all nine T064 forbidden-operation
  cases plus the T065 canonical acceptance case are green. The existing complete
  contract suite remains green.
  The final focused MAJOR-2 suite passed `68/68` with one shared-database historical
  upgrade skip; the unsafe historical-row refusal passed `1/1` against a separate
  pre-010 PostgreSQL database. The live PostgreSQL race, fresh/idempotent migration,
  repository retry, and non-owner RLS/runtime checks passed. The current full suite
  was run with the disposable PostgreSQL qualification database enabled.
  Batch C focused payload, MinIO, package-build, and existing provenance/checksum
  validation passed `20/20`, including the live MinIO conflict test. The final
  T058 live gate passed `1/1` against running PostgreSQL, MinIO, Temporal,
  Redpanda, and Neo4j services. The final clean-volume T043 remediation
  run passed `4/4`; the reversed explicit node order also passed `4/4`, and each of
  the four T043 nodes passed `1/1` on its own fresh PostgreSQL/MinIO pair. The same
  populated environment is explicitly outside the T043 acceptance state model: a
  second full invocation returned `3 passed, 1 failed` when the canonical test
  attempted to re-collect evidence for an already `timeline_ready` case. The focused
  MAJOR-7/Batch-B repository and direct-SQL set passed `8/8`, and the
  non-owner RLS test passed `1/1`. D3's live PostgreSQL integrity/processing/RLS
  matrix passed `3/3`, and its fresh migration search-path regression passed `1/1`.
  Skips require live PostgreSQL, Temporal,
  Redpanda, MinIO, Neo4j, Redis, Vault, or RLS environment variables. No benchmark
  or production fraud metric is claimed.
- US3 T079-T103: the test-first controls, T088-T094 implementation, T095-T102
  lifecycle implementation, and T103 deterministic gate are green. US4
  T104-T130 are now green in their available local/deterministic scopes. Live
  PostgreSQL fresh-migration and non-owner RLS checks remain environment-qualified
  where not covered by the recorded live evidence.
- Payload limits: `RECLAIM_INCIDENT_REPORT_MAX_BYTES` and
  `RECLAIM_WEBHOOK_MAX_BYTES` default to `1048576` bytes; the shared
  `RECLAIM_RAW_OBJECT_MAX_BYTES` boundary defaults to `16777216` bytes. Incident
  report fields are rejected before a transaction or raw-object write, HTTP bodies
  are rejected before FastAPI parsing when over the raw-object limit, webhook bytes
  are checked before JSON parsing, connector raw responses are checked against the
  existing manifest `max_payload_bytes`, and raw object writes enforce the shared
  storage limit. Focused tests observed no transaction, outbox, MinIO, or metadata
  side effects after oversized rejection.
- MinIO immutability: the production client uses an atomic S3 conditional PUT with
  `If-None-Match: *` through the MinIO SDK request executor; deterministic doubles
  use an atomic put-if-absent operation. Same-content duplicates are verified
  idempotently, conflicting content fails closed, and post-write bytes/checksums
  are verified. Local concurrency and live MinIO conflicting-writer checks passed.
- Backend packaging: clean wheel and sdist builds passed; the artifact test inspected
  contents, installed each artifact into an isolated target from a clean working
  directory, and imported API, workflow, worker, evidence, timeline, Razorpay,
  Redpanda, Neo4j, and shared-contract modules from the installed targets.
- Post-remediation full Python suite before T059 was `256 passed, 33 skipped`; the
  post-T059 baseline was `264 passed, 33 skipped`; the post-T069 suite was
  `301 passed, 33 skipped, 10 xfailed`; the post-T073 suite was
  `315 passed, 33 skipped, 10 xfailed`; the post-T074 elevated suite was
  `338 passed, 33 skipped`; and the post-T075 elevated suite is
  `363 passed, 33 skipped`. Skipped tests require live services or optional
  configuration. The T064/T065 expected-red tests are now green; no later-task
  xfails were removed.
- Python: `.venv` Python 3.12.14; direct Ruff and format checks pass for the four
  files in this fix, and `git diff --check` passes. Repository-wide Ruff still
  reports 194 pre-existing findings outside this fix; repository-wide format
  check reports 106 pre-existing files needing formatting. No available mypy or
  pyright executable is installed, so no type-check pass is claimed.
- Node: v22.23.2 and npm 10.9.8 via `npm.cmd`, within the approved `>=20.18 <23`
  range. `npm ci --prefix frontend` completed and reported 12 audit findings (2 low,
  3 moderate, 5 high, 2 critical); no forced audit fix was applied.
- Frontend tooling remains outside T024-T035: `npm run test` exits 1 because no frontend
  test files exist; `npm run typecheck` exits 1 because `frontend/` has no `tsconfig.json`;
  `npm run lint` exits 1 at Next's interactive ESLint setup prompt because no ESLint
  configuration exists.
- Evaluations: not present.
- CI/CD: not configured.
- Final-gate D1/D2 focused coverage passed `39/39` locally, with live Neo4j,
  Redpanda, and the combined Batch-B live test skipped because their environment
  variables were not configured. The live PostgreSQL final-gate suite passed `4/4`:
  12 concurrent tenant-chain writers produced one root and a checksum-verified
  linear chain, tenant partitions remained independent, rollback left no root, and
  a conflicting timeline survived PostgreSQL readback and outbox construction.
- Runtime: temporary dependency-safe validation containers were used, including a
  disposable PostgreSQL instance for the migration-008 fresh migration/runtime-role
  checks; the full future
  Compose topology and operational observability stack were not started.
- Current local service check: Docker Desktop is installed and was started for the
  fresh 2026-09-01 release-gate attempt; no persistent `RECLAIM_*` service
  configuration is retained in the default shell after cleanup. FastAPI 0.115.6 and
  httpx 0.27.2 are installed in `.venv` through the backend dependency definition.
  The test extra uses httpx 0.27.2 because declared litellm 1.55.8 requires httpx
  below 0.28.
- Git: repository is on `main`; the tenant-role remediation, T036-T042 batch, T044-T049
  intake batch, T050-T055 evidence/timeline batch, and T056-T058 event/projection/gate
  batch are committed separately; T074 is committed in the pre-T075 HEAD and T075
  is committed separately in the current HEAD.
  The pre-existing untracked `security-audits/` artifacts remain preserved.
- Extensions: `agent-context` is installed. Staff Review and Project Status are not
  installed; they appear only as uninstalled catalog candidates.

### US3 expected-red ownership

The focused US3 expected-red tests are strict XFAILs, not skipped coverage. Their
future implementation ownership is explicit:

- T082: T092 `action_gateway.state_machine.ActionGatewayStateMachine` for gateway
  transitions, T095 for reconciliation, T096 for verification, and T097 for
  escalation.
- T084: T095 `action_gateway.reconciliation.recover_action` and T101 for durable
  PostgreSQL/Temporal/Redpanda recovery integration.
- T085: T096 `action_gateway.verification.verify_and_route` and T097 for the
  tenant-scoped escalation result.
- T086: T098 `cases.terminal_states.transition_case`.
- T087 diagnostic: T088 `policy.evaluator.evaluate_policy`; T089
  `policy.tenant_configuration.validate_tenant_policy_configuration`; T090
  `approvals.service.authorize_action`; T091 `app.audit.policy.persist_policy_decision`;
  T092 `action_gateway.service.ActionGateway`; T093
  `connectors.simulators.actions.DeterministicActionSimulator`; T094
  `connectors.razorpay.actions.validate_refund_action`; T095
  `action_gateway.reconciliation.recover_action`; T096
  `action_gateway.verification.verify_and_route`; T097
  `escalation.service.EscalationService`; T098
  `cases.terminal_states.transition_case`; T099 `api.control_plane.submit_action`;
  and T100 `workflows.activities.containment.run_containment`.

The T087 diagnostic does not claim that any unavailable PostgreSQL, Temporal,
Redpanda, connector, or financial side effect was exercised.

### Historical US4 expected-red ownership

At the 2026-09-01 T104-T110 test-first checkpoint, the following tests were
strict XFAILs, not skipped coverage. Their implementation ownership was:

- T105: T111 labeled replay runner and T112 canonical fixture.
- T106: T113 deterministic replay variants.
- T107: T114 benchmark metadata, T115 grouped/leakage-safe split validation, and
  T116 held-out sealing/access control.
- T108: T117 benchmark metrics and confidence intervals.
- T109: T120 authoritative Compose topology and safe defaults.
- T110: T122 operator case-review workflow, T123 typed UI commands/read models, and
  T124 live/replay mode selection and labeling.

T111-T124 subsequently supplied those implementation owners, and the T125-T130
gates now cover the available deterministic/operator surfaces. The original
checkpoint did not claim that any live provider, Compose service, browser
workflow, held-out dataset, benchmark corpus, or production metric was exercised.

## Live validation evidence

- On 2026-09-01, a disposable PostgreSQL 16 instance applied migrations 001-009
  from scratch with `ON_ERROR_STOP=1`; migration 009 was reapplied twice idempotently.
  A second database upgraded from the historical migration-007 schema through 009
  successfully. A valid response-less deterministic-only row was accepted with
  explicit `requested_mode`, `terminal_outcome`, and NULL response metadata. The
  public model-analysis tables remained the only grant targets, and `reclaim_app`
  had exactly `SELECT, INSERT` on each table.
  The actual non-owner `reclaim_app` connection was non-owner, non-superuser, and
  `NOBYPASSRLS`; focused migration/runtime validation passed `3/3`, including
  persistence/readback, idempotent retry, conflict rejection, cross-tenant and
  same-tenant cross-case isolation, unvalidated-proposal rejection, and DELETE
  denial. No Action Gateway or financial side effect was attempted.
- PostgreSQL 16 Alpine ran on `localhost:55432`. Migrations
  `001_authoritative_entities.sql`, `002_tenant_isolation.sql`, and the updated `003`
  executed with `ON_ERROR_STOP=1`. A non-owner,
  non-BYPASSRLS `reclaim_app` role proved tenant-a/tenant-b filtering and missing-context
  rejection. Live UoW tests proved commit/rollback for business state plus outbox/inbox;
  duplicate delivery remained tenant/consumer scoped.
- Temporal `temporalio/auto-setup:1.27.2` on `7233` passed repository-validation retry,
  signal, and worker restart/history recovery tests.
- Redpanda `redpandadata/redpanda:v24.3.6` on `9092` (admin `59644`) passed topic and
  real producer/consumer delivery validation.
- Neo4j `5.26-community` on `57474`/`57687`, MinIO
  `RELEASE.2024-12-18T13-15-44Z` on `59000`/`59001`, and Redis `7.4-alpine` on `56379`
  passed their live projection/rebuild, immutable checksum, and bounded coordination
  tests respectively.
- Keycloak `26.0.7` on `58080` imported the `reclaim` realm and returned HTTP 200 for
  OIDC discovery; strict tenant/role verification passed. Vault `1.18.4` on `58200`
  returned HTTP 200 and a narrowly scoped Action-Gateway token read only the test-only
  action secret. No secret or token is committed.
- Docker Desktop exposed approximately 7.62 GiB. Containers were started individually
  with service-specific memory caps rather than starting the full future topology. The
  full Compose topology, observability servers, model providers, Razorpay, and financial
  action systems were not started.
- For T050-T055, fresh temporary PostgreSQL and MinIO services were started with the
  backend migrations and tenant seeds. The live T043 acceptance run passed `4/4`; a
  database query confirmed six tenant-a evidence rows with six raw references and six
  untrusted items, plus six tenant-a timeline rows and six unique dedupe keys. Live MinIO
  checksum/integrity coverage passed `8/8`. A Temporal client connected successfully to
  `localhost:7233`; the existing Temporal worker integration could not construct its
  sandbox in this environment because the installed cryptography binding raised an
  internal import error, so no worker-integration pass is claimed for this batch.
- On 2026-08-31, final new PostgreSQL 16 Alpine and MinIO
  `RELEASE.2024-12-18T13-15-44Z` instances were created with fresh volumes.
  Migrations `001`, `002`, and `003` passed from scratch; only `tenant-a` and
  `tenant-b` were seeded. T043 returned `4 passed` on the fresh volume. The repaired
  harness uses deterministic per-scenario correlation/idempotency namespaces, and the
  direct intake conflict regression confirms that same-key different-content writes
  still fail closed. No production file, contract, or ADR changed.
- For T056-T058, temporary PostgreSQL, MinIO, Redpanda, Neo4j, and Temporal services
  passed the live US1 gate. The gate observed 2 incidents, 2 cases, 8 evidence items,
  7 timeline events, 13 outbox events, and 6 audit records before delivery; all 13
  outbox events were delivered, 12 US1 projection events were applied, duplicate and
  reversed-order delivery converged, and PostgreSQL truth remained unchanged after
  Neo4j reset/rebuild. Exact reviewer evidence is in
  `docs/validation/us1-intake-timeline.md`.
- For Remediation Batch A, the revised T058 gate passed against the running temporary
  PostgreSQL 16, MinIO, Redpanda, Neo4j, and Temporal services. The canonical case was
  started through the authenticated workflow command service, the registered
  production worker executed `case.collect_evidence` and `case.rebuild_timeline`,
  PostgreSQL was re-read after workflow completion as `timeline_ready`, and the live
  MinIO report object checksum/content and PostgreSQL incident/audit references were
  verified. The live production Temporal retry and worker-restart recovery tests
  passed `2/2`; both verified PostgreSQL state and evidence/timeline persistence.
- For Remediation Batch B, migration `003_batch_b_integrity.sql` was applied to the
  running PostgreSQL 16 development service. Live direct-write tests passed `2/2` for
  policy scope/publication immutability and cross-aggregate chain integrity. Live
  Redpanda/Neo4j event tests passed `10/10`; the forged correctly-checksummed event
  was rejected before projection and left Neo4j checkpoints and PostgreSQL outbox
  state unchanged. The live adapter used the documented application-level service
  identity allowlist; no production mTLS/SASL/ACL claim is made.
- For the MAJOR-7 follow-up, fresh and idempotent application of migration `003`
  passed. Direct PostgreSQL authorization cases A-K passed, including rejected
  missing/pending/rejected/expired and cross-scope approvals, rejected deny/escalate,
  successful allow and exact approved execution, and unrelated verification. The
  non-owner `reclaim_app` RLS test passed for global-policy visibility, tenant-B
  filtering, and rejected cross-tenant policy/approval/action writes. The running
  T058 database exposes `policy_decision_id`, `approval_id`, both authorization FKs,
  and the authorization trigger.
- For Remediation Batch C, focused tests covered exact and over-limit incident,
  HTTP, webhook, connector, and raw-object payload boundaries, no-side-effect
  rejection, same-content and conflicting concurrent immutable writes, unsupported
  non-atomic clients, and clean wheel/sdist contents and installed-artifact imports.
  The live MinIO conditional-write test passed with one successful owner and one
  conflicting writer; the final existing checksum/provenance MinIO checks also
  passed. No PostgreSQL/Temporal state migration or contract/ADR change was needed.
- For the final US1 remediation gate, D1 uses a transaction-scoped PostgreSQL
  advisory lock keyed by the authoritative tenant audit-chain scope, a unique
  tenant-root index, and provider-event-id idempotency. D2 persists canonical
  case-level uncertainty and per-event conflict metadata in PostgreSQL, copies the
  same result into `timeline.rebuilt`, and retains it in the existing Neo4j
  projection fields. D1/D2 introduced migration `004_final_gate_integrity.sql` and
  the corresponding columns/index are also declared in migration `001`. D3 now
  derives the approved verified correlation only after HMAC/checksum/provider metadata
  verification, resolves it through migration `005`'s authoritative mapping, stores
  mapping/assertion provenance, and quarantines unresolved/conflicting/cross-tenant
  association without downstream case processing. The architecture review confirmed
  `public` is the authoritative application schema: migration 001's authoritative
  tables and existing live probes use `public`, while migration 002 uses `reclaim`
  only for tenant-context helper functions. Migration 005's unqualified `CREATE
  TABLE` therefore followed the migration role's `reclaim, public` `search_path` and
  placed the mapping in `reclaim`. Corrective migration 006 moves that legacy table
  to `public`, uses explicit public qualification for D3 objects, reasserts forced
  RLS and the tenant policy, and conditionally grants `reclaim_app` only `SELECT,
  INSERT, UPDATE`. The fresh search-path regression applies 001-004 with the public
  baseline, applies 005 with `reclaim, public`, applies 006 twice, and confirms
  exactly one mapping table in `public`; it passed 1/1. The live D3 PostgreSQL/RLS
  matrix passed 3/3 with a non-owner, non-BYPASSRLS role, including Tenant A/B
  read/write isolation. The production webhook boundary intentionally requires an
  authenticated reviewer; only the live-test setup changed to use a legitimate
  reviewer for processing and a trusted service identity for mapping provisioning.
  Production authorization and D3 contract semantics were unchanged.

## Architecture and safety

No architecture or ADR deviation was made. D3's contract/data-model amendment does
not change ownership: PostgreSQL remains authoritative, Temporal remains orchestration,
Redpanda remains transport, and Neo4j remains rebuildable. Remediation Batch B and the MAJOR-7
follow-up changed no approved contract or ADR, Remediation Batch A changed no
approved contract or ADR, Remediation Batch C changed no approved contract or ADR,
and final-gate D1/D2 changed no approved contract or ADR. One implementation
compatibility defect in
the shared optional UTC timestamp validation was fixed so incomplete webhook timestamps
remain representable for quarantine. D3 changed the approved webhook/data-model contract
but requires no ADR because the ownership model is unchanged. The shared contract shape
outside D3 and approved ADRs remain unchanged.
The corrective migrations 006 and 008 are schema-placement/RLS consistency and
scoped-runtime-grant repairs only; no architecture or ADR changed, and no approved
contract changed in this repair. Migration 008 grants only the model-analysis table
permissions required by the existing repository and leaves forced RLS authoritative.
PostgreSQL remains the
business correctness boundary; Temporal owns durable orchestration; Redpanda is only
transport; Neo4j is rebuildable; MinIO stores immutable evidence; Redis is bounded
coordination; Keycloak/OIDC and Vault provide scoped identity/secrets; telemetry is
redacted and correlation-linked; and model/agent capabilities remain proposal-only. No
hosted-model, Razorpay, or other external credentials were available or used. PostgreSQL
RLS remains independent defense in depth; Batch B tightens policy-version writes so
global publication is centrally managed, and the MAJOR-7 trigger preserves RLS on the
authorization lookup. No live financial action was attempted.
No production performance, fraud, or containment metric is claimed.

## Blockers and prerequisites

- Full Compose service smoke, operational observability services, hosted-model
  validation, live Action Gateway execution, and benchmark/evaluation execution
  remain environment- or data-qualified limitations; the local/deterministic
  Compose configuration, frontend workflow, replay/evaluation harness, and
  policy/gateway implementation artifacts are present.
- T044-T055 are the completed intake, evidence, and timeline batch. T056-T058 add
  typed incident/evidence/timeline event emission, tenant-bound Redpanda consumers,
  rebuildable Neo4j projection/checkpoints, and the complete US1 live gate. The event
  transport still requires an authenticated single-tenant service context and validates
  event tenant binding before obtaining a tenant-scoped UoW.
- The first focused US2 remediation batch closed MAJOR-1 and MAJOR-2. D3/MAJOR-5 is now closed
  locally: same-tenant case-only webhook association is hard-cut over to verified
  provider correlation and an authoritative mapping; no insecure fallback remains.
  Original Remediation Batch B closed MAJOR-2 and
  MAJOR-6. The focused MAJOR-7 follow-up closes the approval-to-execution gap with no contract or ADR
  changes and passes its fresh, idempotent, direct-SQL, repository, RLS, event, and
  T058 checks. Batch C closes the payload-limit, atomic-immutability, and backend
  package-discovery findings in focused validation. Final-gate D1 and D2 are closed
  by the live PostgreSQL and focused persistence/event/projection tests. D3 is
  specification-approved and runtime-implemented locally; the
  clean-volume T043 rerun is `4/4` after the acceptance-fixture isolation repair,
  so the Batch C technical gate is PASS. The D3 live release gate is now PASS; T059
  attribution contract coverage, T060-T065 test-first coverage, T066-T069
  deterministic production implementation, T070-T073 bounded model boundaries, T074
  typed response/proposal validation, T075 deterministic proposal validation, and
  T076-T078 model-run persistence/replay fallback/integration-gate work are complete.
  The previous US2 live-gate run exposed missing `reclaim_app` grants on the
  migration-007 model-analysis tables. Corrective migration 008 and its fresh
  non-owner runtime validation close that confirmed blocker locally. The final
  focused MAJOR-2 identity gate is now closed after live PostgreSQL qualification;
  broader live/provider qualification remains separate. T079-T103 are implemented
  and locally validated; no live financial action is claimed.
- Repository-wide Ruff findings and frontend tooling gaps are recorded above and should
  be handled in their owning task scope; they do not block the validated backend
  foundation batch.
- No external credentials are required for the completed local evidence tests; hosted
  model behavior was not exercised. T074 uses the deterministic replay/fake adapter
  for the canonical path; live provider behavior remains unavailable until explicitly
  configured. The T056-T058
  gate used a test-only local Razorpay verifier and replay-labeled evidence simulators;
  it did not claim live Razorpay or production-provider behavior.
- Final US1 release-gate decision on 2026-09-01: UNBLOCK T059. D1 and D2 passed
  fresh live PostgreSQL validation (`4 passed`); D3 passed its live PostgreSQL/RLS
  matrix (`3 passed`) and its search-path regression (`1 passed`); T043 passed
  against fresh PostgreSQL + MinIO (`4 passed`); T058 passed against PostgreSQL +
  MinIO + Temporal + Redpanda + Neo4j (`1 passed`); and the remaining focused
  regressions and quality gates passed as recorded above. T059 subsequently passed
  its focused contract validation and the full Python suite; T060-T065 test-first
  validation passes available checks; T066-T069 production validation passes; T070-T073
  regression validation passes; T074, T075, and T076-T078 validation passes;
  authorized US2 work through T078 is implemented; later status is recorded in the
  T079-T130 milestone entries below.

## Final readiness evidence

Readiness evidence:

- A single feature directory contains a complete `spec.md` for the first vertical slice.
- Requirements define defense-only boundaries, typed tools, policy gates, approvals,
  verification, audit, tenant isolation, and honest evaluation behavior.
- Acceptance scenarios cover one mixed legitimate/attacker incident, forbidden actions,
  duplicate/out-of-order events, idempotent retries, and unresolved escalation.
- The user has reviewed and approved the specification before implementation planning.
- The cross-artifact analysis has no BLOCKER findings; implementation began at T001.
- T001-T008 setup artifacts are present and their local structural, manifest, boundary,
  compile, and provenance checks pass.
- T009-T017 shared contract artifacts and contract tests are complete. T017 was intentionally
  executed before T016 so boundary tests precede the dependent registry service; task IDs
  remain unchanged for requirement traceability.
- T018-T035 are complete: authoritative state, RLS, audit, outbox/inbox, Temporal,
  Redpanda, projection/storage/coordination boundaries, scoped identity/secrets,
  redacted telemetry, control-plane declarations, and forbidden-capability tests are
  implemented. The post-T035 tenant-role remediation is validated by the focused
  adversarial suite and the default full Python suite; live service checks remain
  unavailable in this environment. T056-T058 are complete: live PostgreSQL outbox
  delivery through Redpanda, tenant-bound event consumers, replayable Neo4j projection,
  and the full US1 gate passed against temporary live services. T060-T065 now have
  test-first fixture, property, uncertainty, model-boundary, typed-proposal, and
  forbidden-operation, and canonical acceptance coverage; T066-T069 now provide
  deterministic rules, advisory LightGBM, trusted exposure, source linkage, and
  uncertainty propagation; T070-T078 now provide redaction, a bounded
  provider-neutral response path, strict typed response/provenance parsing,
  side-effect-free typed proposals, deterministic pre-policy proposal validation,
  authoritative model-run/proposal persistence, deterministic replay fallback, and
  the US2 integration gate. At the time of this historical checkpoint, later
  production work remained unstarted.

Current artifacts: the approved/generated FS-001 specification and amended D3
planning/contract package are under `specs/001-incident-intake-containment/`; three
ADRs remain unchanged; and
`tasks.md` contains 133 dependency-ordered tasks with traceability for all 25 functional
requirements. T036-T042 are complete with local contract/property/integration/security
  evidence; T043 and T044-T058 are complete with local and environment-qualified live
  validation. The MAJOR-7 follow-up release gate and Batch C technical gate are
  validated, D3 is specification-approved with live runtime validation complete, and
  T059 is complete as a contract-test-only first batch; T060-T065 test-first coverage,
  T066-T069 deterministic production implementation, the bounded T070-T073 model
  boundary, T074 typed response/proposal validation, T075 deterministic proposal
  validation, and T076-T078 persistence/fallback/integration-gate work are complete;
  T079-T103 are complete through the US3 deterministic gate; T104-T110 test-first
  coverage, T111-T124 implementation, and T125-T130 validation are complete;
  T131-T133 are the final documentation/status/artifact gates.

## First focused US2 remediation — 2026-09-01

The first focused remediation closed only the two requested US2 review findings. MAJOR-1 is
closed: T075 now requires the resolved action connector to match the authoritative
target resource connector, rejects missing or ambiguous connector bindings, and keeps
forged proposal/model metadata from bypassing that authority. MAJOR-2 is closed:
T075 derives a versioned canonical action identity from the authoritative tenant,
case, analysis, action, connector, resource, parameters, amount, and currency; caller
or model-supplied idempotency keys are advisory provenance only. T076 normalizes the
persisted action key to this identity and rejects duplicate valid identities within a
model analysis.

No migration was required. The authoritative action proposal and execution tables
already enforce tenant-scoped uniqueness on `(tenant_id, idempotency_key)`, so
concurrent retries using the derived canonical key converge at the existing database
boundary. No Action Gateway execution, side effect, contract, ADR, review-artifact,
MAJOR-3/MAJOR-4, or payment MINOR remediation was performed.

The focused adversarial and regression validation passed; the complete available US2
regression set passed `144/144` with 4 environment-dependent skips, and the full
available Python suite passed `400` with 37 skips and one existing warning. The four
live model-analysis/PostgreSQL checks remain skipped because their configured database
URLs are absent; this remediation does not claim the final live release gate.

At the end of that first batch, MAJOR-3 and MAJOR-4 remained open and untouched. The
tracked no-payment MINOR remained open and untouched. T079 and US3 remained
blocked/unstarted pending the outstanding review and release gates.

## Second focused US2 remediation — 2026-09-01

This batch closed only MAJOR-3 and MAJOR-4. For MAJOR-3, live-to-replay fallback now
records requested, effective, and final modes separately and rewrites every public
result, outcome record, replay label, terminal status, checksum, and provenance field
to the accepted final mode. Safe attempted-provider identity is retained without raw
provider exception text.

For MAJOR-4, response-less deterministic-only, escalation, and refusal terminals now
produce a typed redacted audit value with explicit terminal outcome and bounded fallback
reason. Provider/model/adapter/response metadata, token usage, cost, and proposals are
NULL or empty rather than fabricated. Migration 009 upgrades existing model-run tables,
supports deterministic-only rows, and preserves append-only audit plus repository
readback behavior. No contract or ADR changed.

Scope was held: MINOR-1, T079/US3, Action Gateway execution, financial/account side
effects, attribution/exposure formulas, and `security-audits/` were not changed.

The new focused suite passed `4/4` with one existing warning; the combined final
T076-T078/remediation/migration set passed `26/26` with four skips; the complete
available US2 regression set passed `112/112` with four skips; and the full Python
suite passed `404/404` with 37 skips and one existing warning. `pip check`, compile
validation, targeted Ruff checks, and `git diff --check` passed. Repository-wide Ruff
reported 10 pre-existing findings and format check reported 17 pre-existing files;
no configured type checker was available. The final configured live release gate is
not claimed because its external database URLs and hosted model credentials remain
absent.

## Final focused US2 MAJOR-2 remediation — 2026-09-01

MAJOR-2 is CLOSED. The root cause was analysis-scoped idempotency identity: the
previous derivation included `analysis_id`, so semantically identical actions from
different analyses could not converge. The corrected versioned SHA-256 identity is
derived from the authoritative tenant, case, action type, connector, resource type
and ID, normalized parameters, and applicable integer minor-unit amount/currency
plus schema/identity versions. It excludes `analysis_id`, run/proposal IDs,
correlation and mode/provider/model metadata, timestamps, token/cost metadata,
rationale, evidence/attribution references, and the caller/model-supplied
idempotency key.

The supplied idempotency key remains intact as advisory provenance on each
analysis/proposal occurrence. PostgreSQL migration `010_canonical_action_identity.sql`
adds the tenant-scoped `canonical_actions` authority with a primary key on
`(tenant_id, canonical_action_id)`, a case-bound occurrence foreign key, forced
tenant RLS, explicit `SELECT, INSERT` runtime grants only, and race-safe
`ON CONFLICT DO NOTHING` persistence. Historical rows that cannot be safely
recomputed are rejected explicitly; they are never silently backfilled. Migration
files 007-009, shared contracts, ADRs, Action Gateway behavior, and side effects
were not changed. `MINOR-1` remains tracked and untouched.

Evidence for closure:

- Focused implementation/regression suite: `68 passed, 1 skipped` (the shared
  database already had migration 010); the historical-row refusal passed `1/1`
  against a separate pre-010 PostgreSQL database.
- Live PostgreSQL 16: concurrent cross-analysis writers produced one canonical
  action row and two proposal occurrences with distinct supplied keys; fresh and
  idempotent migration application, repository retry/readback, non-owner
  `reclaim_app` RLS, cross-tenant/case isolation, and mutation denial passed.
- Full Python suite: `419 passed, 34 skipped, 1 warning`. Ruff check/format,
  compileall, `pip check`, and `git diff --check` passed.

MAJOR-1, MAJOR-3, and MAJOR-4 remain CLOSED. At the time of this historical
checkpoint, T079/US3 remained unstarted and out of scope; no Action Gateway or
financial/account side effect was attempted. The
pre-existing untracked `security-audits/` directory remains preserved.

## US3 T095-T102 completion — 2026-09-01

T095-T102 are implemented; T103 was not started at the time of this baseline.
The durable lifecycle derives
canonical action identity from the approved T075 semantic identity, persists one
tenant/case-bound execution, converges duplicate deliveries, records UNKNOWN as a
first-class state, and reconciles before any retry. Independent merchant-state
verification preserves execution/resource/method/version/checksum provenance;
inconclusive and unresolved results cannot close a case. Escalation is tenant-owned
and captures owner, integer minor-unit exposure/currency, evidence, recommendation,
and provenance. Case outcomes are restricted to `verified_contained`,
`verified_failed`, and `escalated_unresolved`, with append-only audit and outbox
records. Typed APIs and Temporal activities preserve the policy → approval → gateway
→ persistence → reconciliation → verification → escalation → terminal order, with
PostgreSQL remaining authoritative.

Migration `012_us3_action_lifecycle.sql` adds the lifecycle identity, resource,
reconciliation, verification, escalation, correlation, checksums, composite
cross-case/canonical/resource foreign keys, append-only audit trigger, forced tenant
RLS, and least-privilege runtime grants. Historical rows lacking authoritative
identity/provenance fail closed rather than being fabricated. Live financial action
execution remains disabled.

Evidence and quality gates:

- Focused T095-T102 suite: `29 passed, 1 warning`.
- Full available Python suite: `499 passed, 40 skipped, 1 warning`.
- `compileall`, targeted Ruff check/format, `pip check`, and `git diff --check` passed.
- Live PostgreSQL/fresh migration, non-owner RLS, Temporal, Redpanda, and other
  external-service checks were skipped because the required environment/tooling was
  unavailable; no live-service result is claimed.
- `packages/contracts/action_gateway.py` was extended only for required verification
  provenance fields; no ADR was changed. The pre-existing untracked
  `security-audits/` directory was preserved.

## US3 T103 gate completion — 2026-09-01

T103 passed as a deterministic replay qualification. The new gate in
`tests/integration/test_us3_containment_slice.py` exercises typed proposal
validation, policy decisions, approval separation, integer-minor-unit exposure,
the service-only Action Gateway, duplicate convergence, UNKNOWN reconciliation,
merchant verification, escalation, explicit terminal states, and checksum-linked
audit/outbox evidence. No production implementation was changed for T103.

Observed evidence:

- T103 focused gate: `1 passed, 1 warning`.
- Available US3 suite including T103: `87 passed, 1 warning`; T087 acceptance:
  `1 passed, 1 warning`.
- Available US2 regressions: `13 passed, 7 skipped, 1 warning`; contract registry
  and Action Gateway contracts: `14 passed`; migration/RLS unit inventory:
  `4 passed`.
- Full available Python suite: `500 passed, 40 skipped, 1 warning`.
- Targeted Ruff, format check, `pip check`, package/import smoke, and
  `git diff --check` passed. `compileall` exited successfully with only a cache
  traversal notice; no configured type checker was available.
- Live PostgreSQL/fresh migration, non-owner RLS, Temporal, Redpanda, and
  merchant-provider checks remain unqualified because required endpoints,
  credentials, and some CLIs were unavailable. No live-service or live-financial
  result is claimed. The untracked `security-audits/` directory remains preserved.

## Historical US4 T104-T110 test-first completion — 2026-09-01

T104-T110 are complete as a test-only batch. The current replay/evaluation shared
contract is sufficient for T104: `ReplayRun` carries fixture, simulator, policy,
model/provider, seed, environment, mode/label, stage outcomes, terminal state, and
differences; `EvaluationCase` carries provenance, labels, grouped and temporal split
metadata, leakage checks, held-out access policy, outcomes, confidence intervals,
and metric references. No shared contract was changed.

Evidence and quality gates:

- T104-T110 focused suite: `3 passed, 17 xfailed` under the authoritative `.venv`
  environment.
- Combined T104-T110, replay/audit regressions, T103 containment smoke, and T087
  safe-containment acceptance smoke: `21 passed, 17 xfailed, 1 warning`.
- Full available Python suite: `503 passed, 40 skipped, 17 xfailed, 1 warning`.
- Targeted Ruff check and format check passed for all seven new test files; `pip
  check`, package/import smoke, compile validation, and `git diff --check` passed.
  No configured type checker was available.
- The Compose and browser tests are expected-red source-level boundaries because
  T120 and T122-T124 are not implemented. No live Compose topology, browser session,
  provider, held-out dataset, benchmark, or financial side effect was exercised.
- Files changed by this batch are the seven requested test files, `tasks.md`, and
  this status file. No production files, shared contracts, ADRs, constitution,
  or `AGENTS.md` were changed. At this checkpoint, T111+ was not started.
- The pre-existing `packages/contracts/action_gateway.py` working-tree diff remains
  byte-for-byte unchanged and unstaged; `security-audits/` remains untracked and
  untouched.

## US4 T111-T119 implementation — 2026-09-01

T111-T119 are complete. The implementation is limited to replay, evaluation, and
observability boundaries: replay never invokes connectors or the Action Gateway;
live output is accepted only from an explicitly qualified live executor, otherwise
the result is visibly replay-labelled. Evaluation reports preserve actual sample
counts, provenance, failures, abstentions, class balance, currency-separated
integer minor-unit values, confidence intervals, and shortfalls. Held-out payloads
remain sealed behind final-evaluation authorization. Observability is redacted,
correlated, and non-authoritative. No shared contract, ADR, migration, Compose
topology, frontend workflow, or mode-selection implementation was added in this
batch.

Evidence and remaining limits:

- Focused T111-T119 suite: `22 passed, 1 warning`.
- Full available Python suite: `518 passed, 40 skipped, 2 xfailed, 1 warning`.
  The two expected-red tests remain T109/T120 (Compose topology) and
  T110/T122-T124 (operator workflow); no later task was started.
- All 21 exported replay variant names were exercised in a side-effect-free smoke
  run; every result was replay-labelled with `side_effects: false`. Trace smoke
  validation confirmed prompt/raw-evidence dropping and tenant/correlation
  propagation into the existing telemetry adapter.
- `compileall` and targeted Ruff checks pass. The one warning is the existing
  LangGraph pending-deprecation warning. Live PostgreSQL, Temporal, Redpanda,
  Neo4j, provider, connector, and hosted observability checks remain unavailable;
  skipped checks are not claimed as passed.
- The manifest records zero cases because no benchmark corpus was available;
  target counts are retained as targets and no cases were fabricated or padded.
  The recorded performance run measures only a local no-op callable (100 samples,
  5 warmups, warm process): p50/p95 `0.000100000761449337 ms`, throughput
  `5208333.149110136 /s`, zero failures, and no recovery callable. These are not
  intake/replay service results or release SLO evidence.
- At this historical checkpoint, T120+ remained unstarted. The pre-existing
  `packages/contracts/action_gateway.py` working-tree diff and untracked
  `security-audits/` directory remain preserved.

## US4 T120-T124 implementation — 2026-09-02

T120-T124 are complete. At the time of this historical checkpoint, T125 remained
unstarted and the checkpoint did not claim US4 completion. The Compose topology
defines all 21 required services, exposes
only loopback UI/API ingress, keeps internal service networks private, preserves
the Action Gateway credential boundary, and defaults live and financial actions
to false. The CI, security, and evaluation workflows enforce replay-safe defaults,
quality/security/evaluation checks, sealed-data controls, provenance, and diff
hygiene. The operator workspace uses the approved graphite/teal case-review
direction with backend-authoritative read models, integer minor-unit formatting,
typed approval/escalation/replay commands, append-only audit presentation, and
mobile withholding of consequential controls.

T124 mode selection is server-authoritative: LIVE requires qualified provider and
connector state plus observed live execution; unavailable qualification selects
REPLAY or explicit escalation. The UI displays requested, effective, and final
mode, availability reasons, provider/connector state, live execution occurrence,
and separate live-action enablement. No live financial action was enabled or
executed.

Observed evidence:

- Full available Python suite: `529 passed, 40 skipped, 1 warning`.
- T120/T124 focused backend/topology/browser gate: `11 passed`.
- Frontend `typecheck`, ESLint, Vitest (`2 passed`), and production build passed.
- Targeted Ruff check/format, compile validation, `pip check`, workflow Prettier
  validation, Compose `config --quiet`, `git diff --check`, and the browser UI
  source gate passed. Local mypy was not run because it is not installed in the
  existing `.venv`; CI installs it through `backend[test,dev]`.
- Browser visualization was not run because no browser automation tool was
  exposed in this session. Full Compose service smoke was not run because the
  Compose app images are external GHCR references rather than local build
  artifacts; no hosted/live-service result is claimed.
- Impeccable critique, polish, and technical audit were completed in degraded
  single-context mode (no sub-agent/browser tools). The detector returned no
  findings; the polish pass tightened server-authoritative mode labeling, audit
  tab semantics, escalation copy, and mobile touch targets. The audit identified
  no blocking implementation defect, with remaining UX opportunities limited to
  contextual help and power-user shortcuts.
- No contracts, constitution, ADRs, migrations, auth/RLS, or Action Gateway
  implementation files were changed by this batch. The pre-existing dirty work,
  including untracked `security-audits/`, remains preserved and unstaged.

## US4 T125 quickstart validation — 2026-09-02

T125 is complete. At the time of this historical checkpoint, T126 and later
Phase 7 tasks remained unstarted. The T125
acceptance test records the available local deterministic quickstart flow,
replay/live truth, all required replay variants, projection rebuild behavior,
evaluation metadata and held-out controls, observability redaction/configuration,
Compose topology, and reviewer UI traceability. No production behavior was
implemented by T125, and no contract, constitution, ADR, migration,
authentication/RLS, or Action Gateway implementation file was changed for this
validation.

Observed evidence:

- T125 acceptance: `8 passed, 1 warning`; combined T125/regression gate:
  `30 passed, 1 warning`.
- Selected complete-US4 suite: `41 passed, 1 warning`; full available Python
  suite: `537 passed, 40 skipped, 1 warning`.
- Security suite: `58 passed, 1 skipped`; explicit Action Gateway, approval,
  recovery, verification, and tenant authorization checks: `27 passed, 1
  skipped`.
- Explicit fresh-migration, PostgreSQL, and non-owner RLS checks: `5 passed,
  14 skipped` because the required database URLs were not configured.
- Frontend Vitest (`2 passed`), typecheck, ESLint, and production build passed.
- Merged Compose config passed. An isolated Compose project started PostgreSQL,
  Redis, and MinIO and observed all three healthy; the full 21-service stack was
  not started because application images reference unavailable external GHCR
  images.
- Canonical replay was deterministic across two runs, replay-labelled, and had
  no remote side effects. Its terminal state was `escalated_unresolved`; all
  required stage outcomes, attribution labels, exposure fields, approval,
  reconciliation, verification, escalation, and 13 audit records were observed.
- All 21 replay variants were exercised with replay labels, `side_effects:
  false`, and empty remote side effects. Unknown remote results reconciled before
  retry; forbidden proposals were rejected; inconclusive verification escalated.
- Fake Neo4j projection rebuild applied two tenant-scoped events in deterministic
  order and rejected a mixed-tenant input. Live Neo4j checks were skipped because
  connection variables were absent.
- Evaluation manifest actual corpus counts remain zero, with held-out sealing
  and assignment-freeze controls true. A three-case in-memory harness verified
  provenance and metric controls; it is not a benchmark result.
- The operator UI was exercised in the in-app browser with a temporary local
  deterministic read-model stub. Filter, technical-chain expansion, replay
  recording, audit, approval, escalation, exposure, verification, and terminal
  presentation were observed; browser console errors and warnings were empty.
  This was not a live API or merchant-action execution claim.
- Targeted T125 Ruff and format checks passed. Repository-wide Ruff still has
  pre-existing errors/format findings outside T125; they were not modified.

The authoritative evidence record is
`docs/validation/fs001-quickstart.md`. Live PostgreSQL/fresh migration,
non-owner RLS, Temporal, Redpanda, Neo4j, MinIO, Vault, provider/connector,
hosted observability, and full-stack Compose checks remain environment-gated and
are recorded as skips or not run. No final FS-001 release-readiness claim is
made.

## Phase 7 T126-T129 hardening validation — 2026-09-02

T126-T129 are complete. At the time of this historical checkpoint, T130-T133
remained unstarted. This slice added the
deterministic fault matrix, FS-001 security hardening regressions, explicit
Compose/static credential and egress policy declarations, and an actual local
simulator/replay performance baseline. No FS-001 release-ready claim is made.

Observed test evidence:

- T126 fault matrix: `12 passed, 1 warning`; all cases were explicitly labelled
  `deterministic-fault-injected`, with no live dependency claim. PostgreSQL,
  Temporal worker restart, Redpanda, Neo4j, MinIO, Redis, Keycloak, Vault,
  model provider, evidence connector, Action Gateway timeout, and ambiguous
  verification outcomes were covered. Unknown/timeout results reconciled before
  retry; ambiguous verification escalated; duplicate provider invocation was
  not observed in the recovery case.
- T127 hardening: `12 passed, 1 warning`, covering tenant/case scope,
  least privilege, untrusted evidence, PII/secret redaction, approval
  separation and stale authority, audit checksum tampering, arbitrary-network
  and forbidden actions, direct model/API/gateway bypasses, replay truth,
  financial minor-unit/original-source rules, and canonical action identity.
- T128 credential/network boundaries: `13 passed`. The policy matrix grants
  action connector credentials only to `service-account-reclaim-action-gateway`
  and uses explicit symbolic egress allowlists with default deny; no broad
  unrestricted egress target is declared.
- T129 performance: `1 passed, 1 warning`. The measured local warm-process
  baseline used one canonical fixture case, 25 intake repetitions after 3
  warmups, 10 replay repetitions after 2 warmups, and one recovery callable.
  Intake p50/p95 were `0.084100/0.117320 ms` at `10666.894/s`; replay
  p50/p95 were `7.866150/8.921765 ms` at `124.894/s`; recovery time was
  `0.091600 ms`; all measured failure rates were `0.0`. These are callable-level
  local measurements, not production or release-SLO measurements. Details and
  the reproduction command are in `docs/validation/performance-baseline.md`.
- Combined new T126-T129 tests: `38 passed, 1 warning`. Focused T125/T103/T087,
  replay, recovery, connector, and security regressions: `55 passed, 3 skipped,
  1 warning`.
- Full available Python suite: `575 passed, 40 skipped, 1 warning`.

Quality and deployment checks:

- Targeted Ruff lint and format checks, `pip check`, YAML parsing for 13 infra
  YAML files, Compose `config --quiet`, and `git diff --check` passed.
- `compileall` exited successfully; it emitted the existing non-source
  `.pytest_cache` listing notice. Local mypy was unavailable in the existing
  environment. Frontend checks were not rerun because this slice changed no
  frontend files; the prior T125 frontend evidence remains applicable.
- Fresh migration, live PostgreSQL/non-owner RLS, Temporal, Redpanda, Neo4j,
  MinIO, Vault, hosted provider/connector, hosted observability, and full-stack
  Compose checks remain environment-gated. The full-suite skips reflect absent
  service URLs/credentials; no live-service result is inferred.

The runtime hardening fixes normalize unavailable JWKS, Vault, and MinIO
dependencies into safe boundary errors and persist timeout-accepted Action
Gateway responses as `UNKNOWN` before reconciliation. No contracts, ADRs,
constitution, `AGENTS.md`, or migrations were changed by this slice. The
pre-existing dirty Action Gateway contract, untracked approval/action lifecycle
migrations, and intentionally untracked `security-audits/` were preserved and
not staged. Residual deployment debt remains: Docker Compose/static policy
declarations do not enforce production Redpanda mTLS, SASL, ACL, or
principal-binding controls; those must be implemented and validated in a
production deployment.

## FS-001 T130-T133 final acceptance evidence — 2026-09-02

T130-T133 are complete based on observed validation. This closes the authorized
final acceptance, documentation, status, and artifact-gate scope; it does not
claim production readiness or live financial execution.

Observed evidence:

- T130 mixed legitimate/attacker acceptance: `3 passed, 1 warning`. The canonical
  fixture produced explicit outcomes for all required stages, zero forbidden or
  remote side effects, approval identity separation, canonical action identity,
  UNKNOWN reconciliation before retry, mandatory verification, inconclusive
  escalation, integer-minor-unit exposure, audit linkage, replay/live truth, and
  tenant/case isolation. The live request remained replay-labelled because the
  live executor is disabled/unavailable.
- Final focused FS-001 regression matrix: `116 passed, 2 skipped, 1 warning`;
  identity/security/contracts matrix: `67 passed, 4 skipped, 1 warning`;
  migration/RLS/live-database matrix: `1 passed, 14 skipped, 1 warning`.
  Authorization, tenant isolation, approval separation, Action Gateway
  idempotency/reconciliation/verification, replay fallback, financial safety,
  and cross-tenant controls were exercised. Environment-dependent skips were
  caused by absent configured database/service URLs; no live result is inferred.
- Final full Python suite: `578 passed, 40 skipped, 1 warning` in 25.30 seconds.
  The warning is the existing LangGraph pending-deprecation warning. `pip check`,
  compilation, and `git diff --check` passed.
- Frontend Vitest (`2 passed`), lint, typecheck, and production build passed.
  Merged Compose configuration validation passed.
- T131 added the actual-behavior traceability and operator workflow/replay
  documentation at `docs/architecture/fs001-traceability.md`,
  `docs/operator/reviewer-workflow.md`, and
  `docs/operator/replay-and-escalation.md`.
- T133 artifact validation passed with `0 warning(s)`: contract/schema versions,
  migration inventory, task/FR traceability, terminal-state vocabulary,
  disabled live defaults, sealed held-out controls, required artifacts,
  Action Gateway isolation, approval separation, T130 evidence, protected
  governance paths, and diff whitespace all passed.

Qualification and remaining debt:

- The evaluation manifest contains zero available cases, so no benchmark,
  production-fraud, or model-performance claim is made.
- Fresh migration and non-owner RLS checks were attempted but skipped where
  their required database URLs were absent. Full Compose service smoke,
  Temporal/Redpanda/Neo4j/MinIO/Vault/provider/connector/live Action Gateway,
  hosted observability, and hosted-model checks remain environment-qualified.
- Repository-wide Ruff currently reports 15 lint findings and 13 formatting
  findings outside this final slice; T130-targeted Ruff and format checks pass.
  The existing LangGraph and Vite deprecation warnings remain documented.
- Production deployment still requires enforcement and validation of Redpanda
  mTLS, SASL, ACL, and principal-binding controls. The intentionally untracked
  `security-audits/` artifacts and pre-existing dirty Action Gateway contract
  and migrations were preserved and remain unstaged.

Readiness decision: the implementation is ready for the validated local,
deterministic, replay/Test Mode scope of FS-001. It is not a claim that live
production services or financial execution have been validated.

## Phase 8 source-built REPLAY deployment — 2026-09-02

T134-T141 are complete. The repository now provides a source-built, runnable
operator product for the explicitly non-authoritative REPLAY scope. This closes
the gap between the tested domain modules and an application a reviewer can
start and use; it does not qualify live merchant or financial execution.

Delivered behavior:

- A FastAPI entry point exposes liveness, replay-backed readiness, server-qualified
  mode, deterministic replay, and tenant/case-scoped operator read models. The
  demo configuration fails closed unless it is non-production, replay-labelled,
  and has both live-action flags disabled.
- The Next.js operator workspace uses same-origin server routing, opens the
  canonical case by default, labels fixture data as read-only and
  non-authoritative, and does not render approval or escalation command controls
  in REPLAY.
- Local API and web images are built from pinned Python 3.12.8 and Node 22.14.0
  bases. The default low-resource Compose topology runs web, API, and PostgreSQL;
  the broader architecture remains declared behind the `full` profile.
- PowerShell start, status, and stop helpers, deployment troubleshooting, and a CI
  source-build/deployment smoke gate are present. Stopping the demo retains its
  data volumes.
- Fresh PostgreSQL initialization was repaired so webhook tables are normalized
  into `public` and lifecycle verification foreign keys have the required unique
  parent identity. The resulting database has 26 public tables and all three
  checked lifecycle constraints. The canonical UI fixture intentionally is not
  inserted as authoritative business state, so zero case/incident/action/audit
  rows is the expected fresh-demo result.

Observed release evidence:

- Full Python suite: `594 passed, 40 skipped, 1 warning` in 32.52 seconds. The
  skips require separately configured live services; the warning is the existing
  LangGraph pending-deprecation warning.
- Frontend ESLint, TypeScript, Vitest (`2 passed`), Next.js 16.3.4 production
  build, and `npm audit` (`0 vulnerabilities`) passed.
- Default and `full` Compose configuration validation passed. Both local images
  built successfully, and PostgreSQL, API, and web containers reached healthy
  state. API/web logs after the final rebuild and PostgreSQL migration logs had
  no error records.
- HTTP smoke returned readiness `ready`, effective mode `replay`,
  `demo_read_only=true`, `read_only=true`, `authoritative=false`, and zero remote
  side effects through the browser-facing same-origin route.
- Browser validation loaded the complete canonical incident workspace with no
  console errors, no approval/rejection or escalation-resolution controls, and a
  successful simulated replay result labelled `No remote side effects`.
- Fresh schema inspection found 26 public tables, the webhook tables in `public`,
  and the three checked lifecycle constraints. A non-owner RLS transaction saw
  only its selected tenant and rolled back its temporary tenants and role.
- Targeted deployment/migration regression tests (`6 passed`), targeted Ruff,
  CI workflow YAML parsing, and `git diff --check` passed.

Production qualification still requires separately built/accessible full-profile
worker and gateway services; production OIDC and Vault configuration; qualified
merchant connectors; enforced Redpanda mTLS/SASL/ACLs; hosted observability;
backup/restore, load, and service-recovery testing; and an explicit live-action
authorization. No such live action was enabled or executed here.

The disposable failed demo database volumes created during fresh-migration
diagnosis were removed and recreated; they contained no business records. Phase 8
did not modify the constitution, ADRs, or normative specification contracts. The
pre-existing dirty Action Gateway contract was preserved without further edits.

## Phase 9 live-agent specialization — 2026-09-02

FS-002 adds an opt-in fresh-agent path and a reproducible local specialization
workflow while preserving the existing deterministic REPLAY product. The fresh
path is tenant/case scoped, explicitly live-labelled, bounded by the existing
LangGraph/LiteLLM harness, strict response parser, and typed advisory boundary,
and never substitutes a replay response when the provider is unavailable. An
optional typed persistence callback is exposed for wiring the existing PostgreSQL
model-analysis transaction; the local demo store remains a read cache only.

Observed implementation evidence:

- Deterministic dataset generation and validation produced one development row,
  zero validation rows, and zero held-out rows from the currently approved
  canonical source. The manifests record the shortfall and do not make a quality
  claim.
- `soup doctor` passed in the isolated training environment. The Soup data doctor
  completed with one minor generation-marker warning and no truncation risk at the
  configured 4096-token limit.
- A real Soup SFT run completed on CPU for two epochs/two steps using
  `HuggingFaceTB/SmolLM2-135M-Instruct` and LoRA. The observed adapter artifact is
  recorded with SHA-256 in `training/reclaim/manifests/training-run.json`.
  Trainer loss/accuracy telemetry is training telemetry only, not fraud quality.
- The adapter served on loopback after installing the optional Soup serving
  extras. Health and model probes passed. The first RECLAIM route call reached the
  live provider and failed closed because the tiny checkpoint returned invalid
  JSON; no replay substitution or remote side effect occurred. The serving
  manifest records this result and the checkpoint is not promoted.
- Fresh-agent, dataset, evaluation, API, Temporal-boundary, security, and safe
  fresh-versus-replay acceptance checks: `32 passed, 1 warning`. Frontend Vitest
  (`3 passed`), ESLint, TypeScript, and production build passed. Targeted Ruff and
  Python compilation passed.
- Repository-wide Python regression pass: `630 passed, 40 skipped, 1 warning`.
  Skips are the existing environment-gated PostgreSQL, Temporal, Redpanda, Neo4j,
  MinIO, Redis, Vault, and live-service checks.

Qualification and remaining debt:

- Base-versus-specialist evaluation is explicitly `status: not_run` because the
  current dataset has no validation/held-out examples and the live checkpoint
  does not produce an accepted response. The promotion decision is `DON'T SHIP`.
- The fresh route is intentionally disabled by default and rejects production
  configuration. Production still requires wiring the PostgreSQL persistence
  callback, durable Temporal worker deployment, authenticated model serving,
  held-out evaluation, and independent live-action qualification.
- The existing protected dirty paths (`packages/contracts/action_gateway.py`,
  migrations 011/012, and `security-audits/`) were not altered, staged, or reset.
  No commit was created.

## Phase 10 first fully working localhost product flow — 2026-09-02

FS-002 T021 is complete. The default low-resource localhost Compose profile now
drives one authoritative synthetic case through PostgreSQL, deterministic
analysis context, the opt-in fresh LiteLLM provider boundary, typed persisted
model analysis, deterministic policy, approval, Action Gateway simulator,
reconciliation, verification, terminal state, escalation, and append-only audit.
Replay remains available as a separate read-only path and the test Compose
overlay remains replay-only.

Delivered behavior:

- The local product seeds merchant-controlled synthetic evidence and timeline
  rows into PostgreSQL; later requests and operator read models read those rows
  back instead of treating the fixture or an in-memory cache as authority.
- Fresh provider output is strictly tenant/case scoped, rejects model-supplied
  financial authority, persists typed response and provenance through the
  existing model-run/audit repositories, and fails explicitly with
  `MODEL_UNAVAILABLE` when `RECLAIM_SPECIALIST_MODEL` is not configured.
- Approval decisions require the distinct local approver principal and are
  recoverable after API restart from authoritative proposal/policy rows.
- Simulator execution includes the durable unknown-result reconciliation gate;
  verification can terminate as `verified_contained` or route an inconclusive
  result to `escalated_unresolved`. Both paths report zero remote side effects.
- The browser-facing UI exposes seed, fresh analysis, approval, simulator
  execution, escalation, provenance, and audit state while keeping the
  simulator/no-live-effects notice visible.

Observed release evidence:

- Full project Python suite: `632 passed, 40 skipped, 1 warning`.
- Frontend typecheck, Vitest (`3 passed`), ESLint, and Next.js production build
  passed.
- Default and replay test Compose configuration validation passed; source-built
  API/web images and the PostgreSQL-backed smoke stack reached healthy state.
  The existing `reclaim-demo` project was then rebuilt in place with its
  PostgreSQL volume retained; its API and web containers are healthy on ports
  8000 and 3000.
- PostgreSQL smoke covered provider-backed typed analysis and approval through
  verified simulator containment, plus unknown-result reconciliation through an
  open escalation and `escalated_unresolved` terminal state.
- The no-provider path returned explicit `MODEL_UNAVAILABLE` with persisted
  response-less audit and no replay substitution.

This validates the synthetic local product flow only. No live merchant connector,
payment, refund, cancellation, or financial side effect was enabled or executed.
Production qualification still requires the separately deployed Temporal and
connector architecture, authenticated model serving, held-out evaluation, and
explicit live-action authorization. The pre-existing protected dirty Action
Gateway contract, migrations 011/012, and `security-audits/` artifacts were
preserved; no commit was created.

## Phase 11 localhost recovery interaction repair — 2026-09-03

The first browser pass exposed a frontend contract mismatch: valid PostgreSQL
operator-view responses contain nullable provenance and audit metadata, but the
UI treated those fields as optional-only strings. That sent the canonical case
into the unavailable screen, making retry and seed appear inert. The frontend
schemas now accept the authoritative nullable fields, with a regression test
covering the response shape. The seed path also scopes deterministic fixture
provider identities per case so the recovery button can create a second local
synthetic case without violating the tenant-level evidence uniqueness key.

Verification evidence:

- Frontend typecheck, Vitest (`4 passed`), and ESLint passed; the production web
  image was rebuilt.
- The missing-case recovery button created `case-ui-recovery-test-001` and the
  browser rendered its investigation workspace. The canonical case then loaded
  at `http://localhost:3000/cases/case-canonical-demo-001` without a schema error
  or browser console errors.
- Targeted backend acceptance tests (`13 passed`), Ruff, and `git diff --check`
  passed. The API image was rebuilt and the Compose API/web containers remain
  healthy.

No live merchant connector or remote side effect was enabled or executed. The
pre-existing protected dirty paths remain preserved; no commit was created.

## Phase 12 route-backed responsive operator navigation — 2026-09-03

The approved operator UI redesign is implemented for the frontend. The shared
navigation now routes to `/cases`, `/services`, `/reviews`, `/runs`, and `/audit`
with route-aware active states. The case inbox keeps its typed authoritative API
read model, adds local sorting, selection, keyboard shortcuts, case-detail links,
selection/intake drawers, and responsive desktop/tablet/mobile layouts. The
standalone Next development proxy defaults to `127.0.0.1:8000`; Docker can still
override it with `RECLAIM_API_INTERNAL_BASE_URL=http://api:8000`.

Verification evidence:

- Frontend Vitest: `8 passed`; TypeScript, ESLint, and Next production build
  passed. The build includes all five operator routes and the dynamic case detail
  route. The root layout suppresses attribute-only hydration noise from browser
  extensions, and generic non-JSON proxy failures are reported as API
  unavailability rather than an opaque raw 500.
- Playwright browser checks: `5 passed`, covering navigation, URL-backed filters,
  sorting, selection/drawers, keyboard behavior, and desktop/tablet/mobile
  responsive states. The in-app browser was also checked at
  `http://localhost:3000/cases` and `/services` with no console errors.
- The standalone API was not running during the live browser check, so the inbox
  correctly displayed its unavailable state and no incidents were synthesized.
  Fixture-backed browser tests used complete typed API-shaped responses only to
  exercise the interaction contract.
- `git diff --check` passed. Existing unrelated dirty paths were preserved and no
  commit was created.

## Phase 1 pre-deployment identity, secret, and broker security foundation — 2026-09-04

The scoped security foundation is implemented in the existing seams. Production
settings now fail closed unless Keycloak/OIDC issuer and JWKS use HTTPS with
RS256, Vault uses HTTPS, and Redpanda uses SASL_SSL with client TLS files and
deployment-provided SASL credentials. The outbox relay passes the validated
broker security settings to aiokafka; local REPLAY/T153 settings remain
plaintext/replay-safe with live actions disabled. Keycloak's checked-in realm
is HTTPS-only and bearer-only for the API, Vault has a TLS 1.3 production
configuration and read-only policies, and the production Compose overlay
requires deployment-provided control-plane and broker secrets.

n8n credential bootstrap now supports explicit non-secret revisions for staged
HTTP/Kafka credential rotation, verifies managed workflow references before
activation, and never deletes the previous credential. Redpanda production
policy and ACL artifacts declare mandatory mTLS, SASL SCRAM-SHA-512,
default-deny ACLs, and certificate/SASL principal binding. ADR-005 records the
profile separation and rotation decision.

Observed validation:

- Scoped Phase 1 security tests: `11 passed`.
- Combined security, Compose topology, n8n workflow-artifact, Redpanda
  transport, and outbox-relay tests: `140 passed, 2 skipped`; skips were the
  existing live Vault and live Redpanda environment gates.
- Production overlay `docker compose ... --profile production config --quiet`
  passed with test-only placeholder values and paths; no production services or
  credentials were exercised.
- Python compilation passed; the existing `.pytest_cache` listing notice was
  emitted by `compileall`.
- Scoped Ruff check and format checks for the changed Python files passed;
  repository-wide Ruff/format checks remain non-green on pre-existing dirty
  files outside this security slice and were not rewritten.
- `git diff --check` passed. No commit was created and unrelated dirty paths
  were preserved.

This does not claim production broker, identity, Vault, n8n, or live-action
qualification. Certificate issuance, ACL application, secret-manager audit
export, deployment firewall enforcement, and live service validation remain
deployment gates. No live merchant connector or financial side effect was
enabled or executed.

## Phase 2 reliability and operations readiness — 2026-09-04

The scoped operations slice adds production-shaped PostgreSQL custom-format and
MinIO immutable snapshot procedures with SHA-256 manifests and restore integrity
checks, isolated-target-only restore guards, migration rehearsal/rollback
guidance, explicit RPO/RTO/retention settings, and a non-destructive T153 service
recovery check for API, n8n worker, and Redis. Prometheus now loads actionable
backup, PostgreSQL, orchestration-stall, and recovery-escalation alerts; the API
serves a redacted `/metrics` endpoint and readiness gauge. Correlation identifiers
remain available for trace/log lookup while tenant/case identifiers are excluded
from metric labels and raw evidence, prompts, credentials, and narratives remain
redacted.

Observed static validation for this slice:

- Operations readiness/unit, observability, Compose topology, credential/network,
  and T153 recovery-contract tests: `34 passed, 8 warnings`; warnings are existing
  dependency deprecations from the local Python environment.
- PowerShell parser validation: all five backup/restore/recovery scripts `OK`.
- Base plus test Docker Compose config: `OK`.
- Backup policy, alert rules, Prometheus/OTel YAML, and Grafana dashboard parsing:
  `OK`.
- Scoped Ruff check/format, Python compilation, and scoped `git diff --check`: `OK`.

This is static readiness only. No deployment-owned backup, restore rehearsal,
measured RPO/RTO result, live MinIO/PostgreSQL checksum verification, or chaos
restart run was performed in this turn. T153 preserved project/volumes were not
deleted or reset. Live qualification, production secret-manager storage, backup
destination encryption/retention enforcement, and deployment firewall/service
recovery evidence remain open gates.

## Hosted final-round CP06 local model/agent boundary — 2026-09-05

The isolated worktree now contains a provider-neutral model-gateway client and
private FastAPI service, plus a separately authenticated advisory-agent service.
The model gateway owns the installed profile/provider mapping; callers submit
only a strict `ModelAnalysisRequest` and bounded tool results. Extra model,
endpoint, API-key, and other transport fields are rejected. The agent service
accepts only the typed request, calls the provider-neutral gateway client, keeps
the existing fresh-agent parser and advisory-only result contract, and rejects
the merchant-live action environment.

Observed local validation:

- Hosted model transport and agent-boundary tests: `6 passed`.
- Existing fresh-agent API, safety, regression, and runtime tests with the new
  boundary coverage: `19 passed, 8 warnings`; warnings are dependency
  deprecations from the local Python environment.
- Scoped Ruff, Python compilation, and `git diff --check`: passed.

This is a local contract slice, not CP06 hosted lifecycle qualification. No
provider credential, external model endpoint, real OIDC token, n8n workflow,
approval-resume run, Action Gateway execution, terminal recovery, or hosted
provider/model latency/usage/cost evidence was available or used. Fresh-agent
production wiring and full lifecycle recovery remain open until those external
dependencies and evidence are supplied.
