# RECLAIM Project Status

Last updated: 2026-09-01

## Current objective

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
the initial remediation batches for MAJOR-1, MAJOR-3, MAJOR-4, and MAJOR-5 are
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
integration gate; their implementation validation is complete. The US2 live-gate
attempt then exposed a missing runtime grant for both migration-007 model-analysis
tables and stopped at that blocker. Corrective migration 008 now grants the scoped
runtime access, and fresh 001-008 plus non-owner runtime validation pass. US2 still
awaits the FINAL live release gate. The remaining US2 production implementation is
not started.
Remediation Batch C is implemented for
MAJOR-8 payload enforcement,
MAJOR-9 atomic immutable evidence writes, and MAJOR-10 backend artifact discovery;
the focused Batch C checks and the clean-volume T043 remediation rerun pass. The
D3 live release gate is now closed; T059 and T060-T065 test work are complete.
The remaining US2 production work after T078 remains intentionally unstarted.

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
| Application code and infrastructure | Phase 1 Setup, T009-T035 foundation, T044-T058 US1 vertical slice, Remediation B, the MAJOR-7 follow-up, Batch C, final-gate D1/D2 remediation, D3 runtime remediation, and T066-T078 bounded US2 attribution/exposure/model-response/proposal-validation/persistence/fallback batch are present | PostgreSQL authority/RLS, repositories/UoW, serialized tenant audit chains, audit idempotency, outbox/inbox, Temporal, Redpanda delivery with authoritative outbox reconciliation, rebuildable Neo4j case/evidence/timeline projection, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, security boundaries, authenticated intake, Razorpay Test Mode verification/configuration, verified provider correlation, authoritative provider mapping, hard-cutover webhook resolution/quarantine, tenant-bound case workflow commands, production Temporal evidence/timeline activities, versioned evidence connectors/simulators, MinIO/PG evidence persistence, durable incident report provenance, exact-tie deterministic timeline reconstruction, persisted/evented/projection-preserved timeline uncertainty, normalization, policy scope/publication constraints, cross-aggregate chain constraints, PostgreSQL policy-to-execution authorization, configured intake/webhook/raw-object byte limits, atomic MinIO immutable creates, complete backend wheel/sdist runtime package contents, tenant/case-bound rules attribution, fixed-schema fixture-validated advisory LightGBM baseline, deterministic minor-unit exposure, PostgreSQL exposure/attribution repositories, replayable uncertainty/source linkage, deterministic model redaction, versioned analysis-request hand-off, bounded LangGraph harness, LiteLLM provider-neutral adapter seam, fixed read-only model tool registry, strict typed analysis-response parsing, uncertainty/refusal/reference validation, provider/cost provenance, non-executable typed proposal construction, deterministic pre-policy proposal validation, authoritative model-run/proposal provenance persistence, and labeled replay/escalation fallback are present |
| D3 contract/data-model/runtime | Complete; fresh live PostgreSQL/RLS gate passed | `VerifiedProviderCorrelation` v1.0.0, `ProviderCorrelationMapping`, corrective migration `006_provider_correlation_schema.sql`, hard-cutover resolver, quarantine/idempotency behavior, reviewer-context live processing, and non-owner RLS validation pass |
| Foundation Security Review Gate | Passed for the tenant-role binding remediation; T036-T042 test batch complete | Scoped OIDC roles, authenticated UoW propagation, adversarial tests, Redpanda tenant binding, and local validation pass; live service checks were unavailable in this run |
| Tests and benchmark evaluations | T009-T078 plus Remediation B, MAJOR-7 follow-up, Batch C, final-gate D1/D2, D3 validation, and migration-008 runtime-grant validation complete; evaluation not started | Full available Python suite is 386 passed and 33 skipped; focused T076-T078 plus migration-008 coverage is 23/23, including fresh 001-008 migration and non-owner runtime/RLS validation against disposable PostgreSQL. The complete available US2 regression set is 132 passed, and the canonical T065 acceptance case is green. US2 still awaits the FINAL live release gate. No held-out dataset, benchmark, production metric, or containment claim exists |

## Quality state

- Tests: the current elevated default suite is `386 passed, 33 skipped` in the
  project `.venv`; the available environment-safe run emits one LangGraph deprecation
  warning. Focused T076-T078 plus migration-008 runtime-grant coverage passed `23/23`,
  including fresh 001-008 migration and non-owner RLS validation against disposable
  PostgreSQL. The confirmed runtime-grant blocker is closed locally; US2 still awaits
  the FINAL live release gate. The complete available US2 regression set passed
  `132/132`, the focused
  T075 adversarial suite passed `25/25`, and all nine T064 forbidden-operation
  cases plus the T065 canonical acceptance case are green. The existing complete
  contract suite remains green.
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
- Python: `.venv` Python 3.12.13; migration-008 touched-file Ruff and format checks, explicit
  source compileall, git diff check, and pip check pass. Repository-wide Ruff reports
  97 pre-existing findings outside this batch; repository-wide format check reports
  51 pre-existing files needing formatting. No available mypy or pyright executable
  is installed, so no type-check pass is claimed.
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

## Live validation evidence

- On 2026-09-01, a disposable PostgreSQL 16 instance applied migrations 001-008
  from scratch with `ON_ERROR_STOP=1`; migration 008 was also reapplied idempotently
  under a changed `search_path`. The public model-analysis tables remained the only
  grant targets, and `reclaim_app` had exactly `SELECT, INSERT` on each table.
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

- Full Compose, operational observability services, frontend workflow, hosted-model
  validation, policy evaluation, Action Gateway execution, and benchmark/evaluation
  execution remain later tasks and were intentionally not started.
- T044-T055 are the completed intake, evidence, and timeline batch. T056-T058 add
  typed incident/evidence/timeline event emission, tenant-bound Redpanda consumers,
  rebuildable Neo4j projection/checkpoints, and the complete US1 live gate. The event
  transport still requires an authenticated single-tenant service context and validates
  event tenant binding before obtaining a tenant-scoped UoW.
- Remediation Batch A closed MAJOR-1, MAJOR-3, and MAJOR-4. D3/MAJOR-5 is now closed
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
  non-owner runtime validation close that confirmed blocker locally; US2 still
  awaits the FINAL live release gate. T079/US3 remain unstarted.
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
  remaining US2 production work is not started.

## Next milestone: Phase 4 User Story 2 bounded agent analysis and proposals (T070-T078) - T078 implementation complete; live qualification pending

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
  the US2 integration gate. Later production work remains unstarted.

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
  T079+ and the remaining US2 production implementation are not started.

## Focused US2 remediation — 2026-09-01

The focused remediation closed only the two requested US2 review findings. MAJOR-1 is
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

MAJOR-3 and MAJOR-4 remain open and untouched. The tracked no-payment MINOR remains
open and untouched. T079 and US3 remain blocked/unstarted pending the outstanding
review and release gates.
