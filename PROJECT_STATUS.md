# RECLAIM Project Status

Last updated: 2026-08-30

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
T043 canonical acceptance target is now complete: all four acceptance scenarios passed
against fresh live PostgreSQL and MinIO services after the T050-T055 implementation
batch. T044-T058 are complete locally, with the full US1 vertical-slice gate and live
event-delivery/projection validation recorded below; the next queue begins at T059.

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
| Application code and infrastructure | Phase 1 Setup, T009-T035 foundation, and T044-T058 US1 vertical slice present | PostgreSQL authority/RLS, repositories/UoW, audit, outbox/inbox, Temporal, Redpanda delivery, rebuildable Neo4j case/evidence/timeline projection, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, security boundaries, authenticated intake, Razorpay Test Mode verification/configuration, webhook durability, tenant-bound case workflow commands, versioned evidence connectors/simulators, MinIO/PG evidence persistence, normalization, deterministic timeline reconstruction, and the T058 live gate are present |
| Foundation Security Review Gate | Passed for the tenant-role binding remediation; T036-T042 test batch complete | Scoped OIDC roles, authenticated UoW propagation, adversarial tests, Redpanda tenant binding, and local validation pass; live service checks were unavailable in this run |
| Tests and benchmark evaluations | T009-T058 validation complete; evaluation not started | The final default suite is 200 passed and 17 skipped. The live T058 US1 gate is 1 passed; independent live Redpanda, Neo4j, PostgreSQL, and T043 checks are recorded below. No held-out dataset, benchmark, production metric, or containment claim exists |

## Quality state

- Tests: the current no-service T043 acceptance baseline was re-run before this batch
  as `2 passed, 2 skipped`. The final default suite is `200 passed, 17 skipped`; the
  focused T056-T058 suite is `10 passed, 3 skipped`; the live T058 gate is `1 passed`;
  and the existing live T043 acceptance is `4 passed`. Skips require live PostgreSQL,
  Temporal, Redpanda, MinIO, Neo4j, Redis, Vault, or RLS environment variables. No
  benchmark or production fraud metric is claimed.
- Post-remediation default suite: `69 passed, 11 skipped` in `0.66s`; skipped tests
  require live PostgreSQL, Temporal, Redpanda, MinIO, Neo4j, Redis, Vault, or RLS
  environment variables. Focused authorization/UoW/foundation checks passed with
  `17 passed, 2 skipped`, and the focused OIDC/UoW set passed with `15 passed`.
- Python: `.venv` Python 3.12.13; `compileall` passed with only the benign existing
  `.pytest_cache` directory-listing message. Ruff passed on all T056-T058 touched
  Python paths, including formatting. Repository-wide Ruff 0.8.6 reports 22 existing
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
- Runtime: temporary dependency-safe validation containers were used; the full future
  Compose topology and operational observability stack were not started.
- Current local service check: Docker Desktop was available through its installed
  executable for this validation run, but no persistent `RECLAIM_*` service configuration
  is present in the default shell. FastAPI 0.115.6 and httpx 0.27.2 are installed in
  `.venv` through the backend dependency definition. The test extra uses httpx 0.27.2
  because declared litellm 1.55.8 requires httpx below 0.28.
- Git: repository is on `main`; the tenant-role remediation, T036-T042 batch, T044-T049
  intake batch, T050-T055 evidence/timeline batch, and T056-T058 event/projection/gate
  batch are committed separately.
  The pre-existing untracked `security-audits/` artifacts remain preserved.
- Extensions: `agent-context` is installed. Staff Review and Project Status are not
  installed; they appear only as uninstalled catalog candidates.

## Live validation evidence

- PostgreSQL 16 Alpine ran on `localhost:55432`. Migrations `001_authoritative_entities.sql`
  and `002_tenant_isolation.sql` executed with `ON_ERROR_STOP=1`. A non-owner,
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
- For T056-T058, temporary PostgreSQL, MinIO, Redpanda, Neo4j, and Temporal services
  passed the live US1 gate. The gate observed 2 incidents, 2 cases, 8 evidence items,
  7 timeline events, 13 outbox events, and 6 audit records before delivery; all 13
  outbox events were delivered, 12 US1 projection events were applied, duplicate and
  reversed-order delivery converged, and PostgreSQL truth remained unchanged after
  Neo4j reset/rebuild. Exact reviewer evidence is in
  `docs/validation/us1-intake-timeline.md`.

## Architecture and safety

No architecture or ADR deviation was made. One implementation compatibility defect in
the shared optional UTC timestamp validation was fixed so incomplete webhook timestamps
remain representable for quarantine; contract shape and approved ADRs are unchanged.
PostgreSQL remains the
business correctness boundary; Temporal owns durable orchestration; Redpanda is only
transport; Neo4j is rebuildable; MinIO stores immutable evidence; Redis is bounded
coordination; Keycloak/OIDC and Vault provide scoped identity/secrets; telemetry is
redacted and correlation-linked; and model/agent capabilities remain proposal-only. No
hosted-model, Razorpay, or other external credentials were available or used. PostgreSQL
RLS migration behavior is unchanged; live RLS checks were skipped because their
environment variables were unavailable. No live financial action was attempted. No
production performance, fraud, or containment metric is claimed.

## Blockers and prerequisites

- Full Compose, operational observability services, frontend workflow, model gateway,
  live Razorpay Test Mode, and benchmark/evaluation execution remain later tasks and
  were intentionally not started.
- T044-T055 are the completed intake, evidence, and timeline batch. T056-T058 add
  typed incident/evidence/timeline event emission, tenant-bound Redpanda consumers,
  rebuildable Neo4j projection/checkpoints, and the complete US1 live gate. The event
  transport still requires an authenticated single-tenant service context and validates
  event tenant binding before obtaining a tenant-scoped UoW.
- Repository-wide Ruff findings and frontend tooling gaps are recorded above and should
  be handled in their owning task scope; they do not block the validated backend
  foundation batch.
- No external credentials are required for the completed local evidence tests; live
  provider/model behavior remains unavailable until explicitly configured. The T056-T058
  gate used a test-only local Razorpay verifier and replay-labeled evidence simulators;
  it did not claim live Razorpay or production-provider behavior.

## Next milestone: Phase 4 User Story 2 attribution and exposure (T059-T078)

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

Current artifacts: the approved/generated FS-001 specification and planning package are
under `specs/001-incident-intake-containment/`; three ADRs remain unchanged; and
`tasks.md` contains 133 dependency-ordered tasks with traceability for all 25 functional
requirements. T036-T042 are complete with local contract/property/integration/security
  evidence; T043 and T044-T058 are complete with local and environment-qualified live
  validation. T059 is the next dependency-safe queue; no T059+ implementation was started.
