# RECLAIM Project Status

Last updated: 2026-08-30

## Current objective

Implement the approved FS-001 Spec Kit vertical slice from the first dependency-ordered
setup task onward:

`incident intake → evidence → Temporal workflow → bounded agent analysis → policy →
Action Gateway → verification → audit`

Application implementation has completed Phase 2 Foundation through T035: Phase 1
setup, the T009-T017 shared-contract boundary, the T018-T023 authoritative-state/audit/
event-delivery batch, and T024-T035 runtime/security boundaries are complete. No User
Story 1 behavior is claimed complete until its task and verification evidence exist.

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
| Application code and infrastructure | Phase 1 Setup and T009-T035 foundation complete | PostgreSQL authority/RLS, repositories/UoW, audit, outbox/inbox, Temporal, Redpanda, Neo4j, MinIO, Redis, Keycloak/OIDC, Vault, observability, control-plane, and security boundaries are present |
| Tests and benchmark evaluations | T009-T035 validation complete; evaluation not started | 70 tests pass with live local validation services; no held-out dataset, benchmark, production metric, or containment claim exists |

## Quality state

- Tests: with all local validation services configured, `70 passed in 14.68s`. This
  includes unit, contract, security, failure-path, live PostgreSQL, Temporal, Redpanda,
  Neo4j, MinIO, Redis, Vault, and foundation-gate tests. No benchmark or production
  fraud metric is claimed.
- Python: `.venv` Python 3.12.13; targeted backend/application/projection/workflow/test
  `compileall` passed. Targeted T024-T035 Ruff using available Ruff 0.16.2 passed.
- Repository-wide Ruff reports 27 existing issues in T018-T023-era files (mostly import
  ordering/UTC style, plus one unused import and one long line); those unrelated files
  were not reformatted in this batch.
- Backend mypy: the declared `mypy==1.14.1` install was attempted, but the download
  stalled and was aborted; no mypy pass is claimed.
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
- Git: repository is on `main`; T024-T035 changes are being prepared in coherent commits.
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
hosted-model, Razorpay, or other external credentials were available or used. No live
financial action was attempted. No production performance, fraud, or containment metric
is claimed.

## Blockers and prerequisites

- Full Compose, operational observability services, frontend workflow, model gateway,
  Razorpay Test Mode, and benchmark/evaluation execution remain later tasks and were
  intentionally not started.
- Repository-wide Ruff findings and frontend tooling gaps are recorded above and should
  be handled in their owning task scope; they do not block the validated backend
  foundation batch.
- No external credentials are required for the completed local foundation tests; live
  provider/model behavior remains unavailable until explicitly configured.

## Next milestone: Phase 3 User Story 1 implementation (T036 onward)

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
  implemented. The full local validation matrix passed with 70 tests.

Current artifacts: the approved/generated FS-001 specification and planning package are
under `specs/001-incident-intake-containment/`; three ADRs remain unchanged; and
`tasks.md` contains 133 dependency-ordered tasks with traceability for all 25 functional
requirements. The next dependency-safe group is T036-T042 (parallel US1 intake/webhook,
timeline, evidence, provenance, and security tests), followed by T043, T044-T049,
T050-T057, and T058. No task beyond T035 was started in this batch.
