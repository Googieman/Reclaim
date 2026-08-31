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
on 2026-09-01. Current local validation is recorded below; live PostgreSQL/RLS
validation was unavailable in this environment. Original Remediation Batch B for
MAJOR-2 and MAJOR-6 is complete locally. Its follow-up review kept MAJOR-7 open;
the focused approval-to-execution remediation and validation are recorded below.
T059 remains blocked pending the release gate; no T059 or US2 implementation was
started. Remediation Batch C is implemented for MAJOR-8 payload enforcement,
MAJOR-9 atomic immutable evidence writes, and MAJOR-10 backend artifact discovery;
the focused Batch C checks and the clean-volume T043 remediation rerun pass. T059
remains blocked by the explicit release-gate instruction.

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
  remediation only, with T059 and US2 remaining blocked and out of scope.

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
| Application code and infrastructure | Phase 1 Setup, T009-T035 foundation, T044-T058 US1 vertical slice, Remediation B, the MAJOR-7 follow-up, Batch C, final-gate D1/D2 remediation, and D3 runtime remediation are present | PostgreSQL authority/RLS, repositories/UoW, serialized tenant audit chains, audit idempotency, outbox/inbox, Temporal, Redpanda delivery with authoritative outbox reconciliation, rebuildable Neo4j case/evidence/timeline projection, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, security boundaries, authenticated intake, Razorpay Test Mode verification/configuration, verified provider correlation, authoritative provider mapping, hard-cutover webhook resolution/quarantine, tenant-bound case workflow commands, production Temporal evidence/timeline activities, versioned evidence connectors/simulators, MinIO/PG evidence persistence, durable incident report provenance, exact-tie deterministic timeline reconstruction, persisted/evented/projection-preserved timeline uncertainty, normalization, policy scope/publication constraints, cross-aggregate chain constraints, PostgreSQL policy-to-execution authorization, configured intake/webhook/raw-object byte limits, atomic MinIO immutable creates, and complete backend wheel/sdist runtime package contents are present |
| D3 contract/data-model/runtime | Complete locally; live PostgreSQL/RLS validation unavailable in this run | `VerifiedProviderCorrelation` v1.0.0, `ProviderCorrelationMapping`, migration `005_provider_correlation_authority.sql`, hard-cutover resolver, quarantine/idempotency behavior, replay fixtures, and focused D3 tests are present and pass locally |
| Foundation Security Review Gate | Passed for the tenant-role binding remediation; T036-T042 test batch complete | Scoped OIDC roles, authenticated UoW propagation, adversarial tests, Redpanda tenant binding, and local validation pass; live service checks were unavailable in this run |
| Tests and benchmark evaluations | T009-T058 plus Remediation B, MAJOR-7 follow-up, Batch C, final-gate D1/D2, and D3 focused validation complete; evaluation not started | Current default suite is 254 passed and 32 skipped; D3 focused/unit/contract validation is 51 passed and 3 live PostgreSQL skips; T043 acceptance is 2 passed and 2 live PostgreSQL skips; current T058 live gate is skipped because its service environment is unavailable. No held-out dataset, benchmark, production metric, or containment claim exists |

## Quality state

- Tests: the current default suite is `254 passed, 32 skipped` in the project `.venv`.
  Batch C focused payload, MinIO, package-build, and existing provenance/checksum
  validation passed `20/20`, including the live MinIO conflict test. The prior
  recorded T058 run passed `1/1` against running live services; the current T058
  invocation is skipped because live services are not configured. The final clean-volume T043 remediation
  run passed `4/4`; the reversed explicit node order also passed `4/4`, and each of
  the four T043 nodes passed `1/1` on its own fresh PostgreSQL/MinIO pair. The same
  populated environment is explicitly outside the T043 acceptance state model: a
  second full invocation returned `3 passed, 1 failed` when the canonical test
  attempted to re-collect evidence for an already `timeline_ready` case. The focused
  MAJOR-7/Batch-B repository and direct-SQL set passed `8/8`, and the
  non-owner RLS test passed `1/1`. D3 mapping, webhook, and replay-focused tests
  passed locally; its live PostgreSQL integrity/processing/RLS tests were skipped
  because the required URLs are not configured. Skips require live PostgreSQL, Temporal,
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
- Post-remediation full Python suite: `254 passed, 32 skipped` in `14.62s` in the
  project `.venv`; skipped tests require live services or optional configuration.
- Python: `.venv` Python 3.12.13; final-gate touched-file Ruff and format checks,
  compileall, and git diff check pass; pip check reports no broken requirements.
  Repository-wide Ruff
  0.8.6 reports 22 existing
  findings outside the completed batch; repository-wide format check reports 18
  pre-existing files needing formatting. Existing findings remain in their owning scope.
- Backend mypy/pyright: no type-check executable is installed in this environment; no
  type-check pass is claimed.
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
- Runtime: temporary dependency-safe validation containers were used; the full future
  Compose topology and operational observability stack were not started.
- Current local service check: no Docker executable and no persistent `RECLAIM_*` service
  configuration are available in the default shell for this validation run. FastAPI 0.115.6
  and httpx 0.27.2 are installed in
  `.venv` through the backend dependency definition. The test extra uses httpx 0.27.2
  because declared litellm 1.55.8 requires httpx below 0.28.
- Git: repository is on `main`; the tenant-role remediation, T036-T042 batch, T044-T049
  intake batch, T050-T055 evidence/timeline batch, and T056-T058 event/projection/gate
  batch are committed separately.
  The pre-existing untracked `security-audits/` artifacts remain preserved.
- Extensions: `agent-context` is installed. Staff Review and Project Status are not
  installed; they appear only as uninstalled catalog candidates.

## Live validation evidence

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
  association without downstream case processing. Focused local D3 validation passed;
  live PostgreSQL/RLS validation could not run because no database URLs or Docker
  executable are available in this environment.

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

- Full Compose, operational observability services, frontend workflow, model gateway,
  live Razorpay Test Mode, and benchmark/evaluation execution remain later tasks and
  were intentionally not started.
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
  so the Batch C technical gate is PASS. T059 remains blocked by the explicit
  release-gate instruction; no US2 or T059 implementation was started.
- Repository-wide Ruff findings and frontend tooling gaps are recorded above and should
  be handled in their owning task scope; they do not block the validated backend
  foundation batch.
- No external credentials are required for the completed local evidence tests; live
  provider/model behavior remains unavailable until explicitly configured. The T056-T058
  gate used a test-only local Razorpay verifier and replay-labeled evidence simulators;
  it did not claim live Razorpay or production-provider behavior.

## Next milestone: Phase 4 User Story 2 attribution and exposure (T059-T078) - blocked

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
  and the full US1 gate passed against temporary live services.

Current artifacts: the approved/generated FS-001 specification and amended D3
planning/contract package are under `specs/001-incident-intake-containment/`; three
ADRs remain unchanged; and
`tasks.md` contains 133 dependency-ordered tasks with traceability for all 25 functional
requirements. T036-T042 are complete with local contract/property/integration/security
  evidence; T043 and T044-T058 are complete with local and environment-qualified live
  validation. The MAJOR-7 follow-up release gate and Batch C technical gate are
  validated, D3 is specification-approved with local runtime validation complete, and T059 remains held pending explicit release-gate direction; no T059+
  or US2 implementation was started.
