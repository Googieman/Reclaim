# RECLAIM Project Status

Last updated: 2026-08-30

## Current objective

Implement the approved FS-001 Spec Kit vertical slice from the first dependency-ordered
setup task onward:

`incident intake → evidence → Temporal workflow → bounded agent analysis → policy →
Action Gateway → verification → audit`

Application implementation is proceeding with Phase 2 Foundation; Phase 1 setup, the
T009-T017 shared-contract boundary, and the T018-T023 authoritative-state/audit/event
delivery batch are complete. No later business behavior is claimed complete until its
task and verification evidence exist.

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
| Application code and infrastructure | Phase 1 Setup, T009-T017 contracts, and T018-T023 PostgreSQL/audit/event-delivery foundation complete | Authoritative entity and tenant-isolation migrations, transaction-local tenant context, explicit PostgreSQL repositories/UoW, checksum-linked append-only audit chain, transactional outbox, and tenant-aware inbox/idempotency persistence are present; workflow, transport runtime, storage, identity, and later business services are not yet implemented |
| Tests and benchmark evaluations | Contract, foundation, and T022-T023 persistence-contract validation started; live database integrations/evaluations not started | 23 T009-T017 contract tests, 5 T018-T021 foundation unit tests, and 9 T022-T023 transaction/idempotency tests pass (37 total); no live PostgreSQL migration/integration run, held-out dataset, or evaluation run exists yet |

## Quality state

- Tests: 23 T009-T017 contract tests, 5 T018-T021 foundation unit tests, and 9 T022-T023
  persistence-contract tests pass (37 total); targeted Python compile checks pass. The
  T022-T023 integration tests use a transaction-aware PostgreSQL protocol double to
  validate repository SQL/protocol behavior and are not live database validation. The
  existing pytest-asyncio fixture-loop-scope deprecation warning is resolved by explicit
  function scope in the root and test-specific pytest configuration. Migration execution
  against PostgreSQL remains unvalidated in this environment because no `psql`, Docker
  CLI/service, or accessible WSL distribution is available.
- Evaluations: not present.
- CI/CD: not configured.
- Runtime: No Compose topology has been implemented or validated yet; PostgreSQL is not
  available through the current shell for migration execution.
- Git: repository is on `main`; the T009-T017 and T018-T023 foundation changes are
  committed by the end of this batch, with the working tree expected clean.
- Extensions: `agent-context` is installed. Staff Review and Project Status are not
  installed; they appear only as uninstalled catalog candidates.

## Blockers and prerequisites

- Staff Review and Project Status Spec Kit extensions are unavailable and cannot be
  invoked until explicitly installed.
- The cross-artifact readiness analysis found no BLOCKER findings. The stale planning-phase
  sentence in `plan.md` has been corrected. The shell aliases `python`/`python3` are
  unavailable; validation used the bundled Python environment. The bundled environment
  has no Ruff executable, so no lint result is claimed. PostgreSQL migration execution is
  deferred until a database foundation integration environment is available; live
  migration validation remains pending.
- Razorpay Test Mode credentials, model-provider credentials, and a Docker daemon are
  environment prerequisites for integration execution; credentials and Docker availability
  were not revalidated in this batch.

## Next milestone: Phase 2 Foundation implementation (T024-T035 next; T018-T023 complete)

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
- T018-T023 are complete: migrations cover authoritative FS-001 entities and delivery
  hand-off tables; tenant context and RLS policies enforce isolation; explicit repositories
  and a transaction-scoped unit of work keep writes in PostgreSQL; the audit chain is
  append-only and checksum-linked; outbox enqueue participates in that transaction; and
  tenant/consumer inbox claims are duplicate-safe with checksum conflict detection. The
  9 new tests cover rollback, atomic commit, duplicate delivery, retry, tenant/consumer
  scoping, and identity conflicts. Live PostgreSQL migration validation remains pending.

Current artifacts: FS-001 specification and planning package are approved/generated at
`specs/001-incident-intake-containment/`. Five high-impact clarification answers were
integrated, planning completed, and three ADRs recorded. On 2026-08-30, the planning
evaluation sizing was corrected to target a benchmark corpus of at least 500 cases
when feasible and at least 100 held-out cases, preferably 150 or more, with leakage
controls, composition requirements, sealed scenarios, confidence intervals, and
honest shortfall reporting. On 2026-08-30, `tasks.md` was generated with 133 tasks
covering the approved architecture and FS-001 requirements. T001-T008 setup implementation,
T009-T017 contract implementation, and T018-T023 authoritative-state/audit/event-delivery
foundation implementation are complete; no user-story behavior, live database integration,
or operational metrics are claimed complete. The feature specification metadata records
`Status: Approved`, consistent
with this project status and the recorded approval.
