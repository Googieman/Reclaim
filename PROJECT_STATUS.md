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
the T036-T042 US1 contract/property/integration/security test batch is complete. No
US1 evidence or timeline implementation is claimed complete. The T043 canonical
acceptance target is present but intentionally red because its required evidence runtime
is not implemented. The first coherent US1 implementation batch completed T044 and T047
locally; Razorpay, evidence, timeline, and workflow runtime tasks remain pending.

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
| Application code and infrastructure | Phase 1 Setup, T009-T035 foundation, and T044/T047 intake batch present | PostgreSQL authority/RLS, repositories/UoW, audit, outbox/inbox, Temporal, Redpanda, Neo4j, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, security boundaries, authenticated intake, and authoritative incident/case creation are present; evidence/timeline runtime remains pending |
| Foundation Security Review Gate | Passed for the tenant-role binding remediation; T036-T042 test batch complete | Scoped OIDC roles, authenticated UoW propagation, adversarial tests, Redpanda tenant binding, and local validation pass; live service checks were unavailable in this run |
| Tests and benchmark evaluations | T009-T042 validation complete; T043 target added; evaluation not started | Baseline was 128 passed and 12 skipped. The T044/T047 focused service batch is 5 passed and 1 live skip; the full suite now has an expected T043 collection error until evidence runtime exists. No held-out dataset, benchmark, production metric, or containment claim exists |

## Quality state

- Tests: the pre-T043 default suite was `128 passed, 12 skipped in 0.70s`; the focused
  T036-T042 suite is `62 passed, 2 skipped in 0.28s`. The latest T044/T047 focused
  service suite is `5 passed, 1 skipped` (live PostgreSQL unavailable), and the
  canonical T043 suite fails during collection because `app.evidence.orchestrator`
  is not implemented yet. Skips require live PostgreSQL,
  Temporal, Redpanda, MinIO, Neo4j, Redis, Vault, or RLS environment variables. A
  previous all-service foundation result of `70 passed in 14.68s` remains historical
  evidence. No benchmark or production fraud metric is claimed.
- Post-remediation default suite: `69 passed, 11 skipped` in `0.66s`; skipped tests
  require live PostgreSQL, Temporal, Redpanda, MinIO, Neo4j, Redis, Vault, or RLS
  environment variables. Focused authorization/UoW/foundation checks passed with
  `17 passed, 2 skipped`, and the focused OIDC/UoW set passed with `15 passed`.
- Python: `.venv` Python 3.12.13; targeted backend/application/projection/workflow/test
  `compileall` passed. Targeted T024-T035 Ruff using available Ruff 0.16.2 passed.
- Repository-wide Ruff using Ruff 0.16.2 reports the same 39 existing issues in
  Spec Kit tooling, provenance/audit, and repository foundation files; the touched
  T043/T044/T047 Python paths pass Ruff and formatting checks. Existing findings remain
  in their owning implementation scope.
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
- Current local service check: the Docker CLI is not available on PATH, FastAPI is not
  installed in the active `.venv`, and no `RECLAIM_DATABASE_URL` is configured; no live
  T044 API or PostgreSQL intake validation is claimed.
- Git: repository is on `main`; the tenant-role remediation and T036-T042 batch remain
  committed separately, while the T043/T044/T047 work is currently in the working tree.
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

## Architecture and safety

No architecture or approved contract/ADR deviation was made. PostgreSQL remains the
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
  Razorpay Test Mode, and benchmark/evaluation execution remain later tasks and were
  intentionally not started.
- T044 and T047 are the first implementation batch: authenticated intake, authoritative
  incident/case creation, duplicate identity handling, intake audit, and the
  `incident.accepted` transactional outbox hand-off are present. The API test is skipped
  because FastAPI is declared but not installed in the active virtual environment; the
  live PostgreSQL intake test is skipped because `RECLAIM_DATABASE_URL` is absent. No
  Razorpay handler, evidence connector/orchestrator, timeline runtime, Temporal intake
  activity, or event consumer was introduced. The existing Redpanda transport wiring
  still requires an authenticated single-tenant service context and validates event
  tenant binding before obtaining a tenant-scoped UoW.
- Repository-wide Ruff findings and frontend tooling gaps are recorded above and should
  be handled in their owning task scope; they do not block the validated backend
  foundation batch.
- No external credentials are required for the completed local foundation tests; live
  provider/model behavior remains unavailable until explicitly configured.

## Next milestone: Phase 3 User Story 1 implementation (T045/T046/T048 onward)

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
  unavailable in this environment.

Current artifacts: the approved/generated FS-001 specification and planning package are
under `specs/001-incident-intake-containment/`; three ADRs remain unchanged; and
`tasks.md` contains 133 dependency-ordered tasks with traceability for all 25 functional
requirements. T036-T042 are complete with local contract/property/integration/security
evidence; T043 is an unchecked executable target; T044 and T047 are complete from the
first implementation batch; T045, T046, T048, T049, and later US1 tasks remain pending.
