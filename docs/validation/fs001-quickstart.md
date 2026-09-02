# FS-001 Quickstart Validation — T125

## Scope and provenance

This document records the observed results of T125 only. It does not implement
T126 or any Phase 7 hardening task, and it does not claim final FS-001 release
readiness. Evidence was gathered on 2026-09-02 in the local checkout on branch
`main`, before the T125 evidence commit, at HEAD
`9170e4e9c5fc4ce15ae5997368c937ea5659e364`.

No contract, constitution, ADR, migration, authentication/RLS, or Action
Gateway implementation change was made for T125. Existing unrelated working
tree changes and the intentionally untracked `security-audits/` directory were
preserved and were not included in the T125 evidence commit.

## Environment

Observed locally:

- Windows PowerShell.
- Python 3.12.13 from `.venv`.
- Node.js v24.19.0 and npm 11.17.0.
- Docker 29.6.2 and Docker Compose v5.3.1.
- Docker daemon: 12 CPUs and 8,184,348,672 bytes reported memory.
- No `RECLAIM_*` environment variables were configured.
- The frontend package declares Node `>=20.18.0 <23`; the observed Node 24.19.0
  is outside that declared range. The recorded frontend checks still passed.

## Commands and observed results

The following results were observed during this validation session:

| Check | Result |
|---|---|
| `pytest tests/acceptance/test_quickstart_flow.py -q --tb=short` | 8 passed, 1 warning |
| T125 plus Compose, browser, replay, evaluation, US3, and safe-containment regressions | 30 passed, 1 warning |
| Selected complete-US4 suite | 41 passed, 1 warning |
| Full available Python suite: `pytest -q --tb=short` | 537 passed, 40 skipped, 1 warning |
| `pytest tests/security -q --tb=short` | 58 passed, 1 skipped |
| Neo4j projection tests | 6 passed, 2 skipped |
| Explicit Action Gateway, approval, recovery, verification, and tenant authorization checks | 27 passed, 1 skipped |
| Explicit fresh-migration, PostgreSQL, and non-owner RLS checks | 5 passed, 14 skipped |
| Frontend Vitest | 2 passed |
| Frontend typecheck | Passed |
| Frontend ESLint | Passed |
| Frontend production build | Passed |
| T109/T110 source and workflow gate | 2 passed |
| T103/T087 containment and recovery gate | 2 passed, 1 warning |
| Targeted Ruff check and format check for the T125 test | Passed; file already formatted |
| Compose merged-file `config --quiet` | Passed |
| `git diff --check` | Passed |

The existing LangGraph pending-deprecation warning was present in the Python
checks. The frontend test run also emitted the existing Vite CJS API
deprecation warning.

Repository-wide Ruff was checked but is not clean in the pre-existing working
tree: it reported 17 existing errors and the format check reported 13 existing
files needing formatting outside the T125 test. Those unrelated findings were
not modified by T125.

## Compose and service health

The merged Compose configuration parsed successfully and contained all 21
declared services:

`web`, `api`, `workflow-worker`, `model-gateway`, `attribution`,
`evidence-connectors`, `action-gateway`, `postgres`, `temporal`, `redpanda`,
`neo4j`, `minio`, `redis`, `keycloak`, `vault`, `otel-collector`, `prometheus`,
`grafana`, `loki`, `langfuse`, and `mlflow`.

The configuration inspection observed loopback-only host exposure for the web
and API ports, internal app/data/action-boundary/observability networks,
disabled live and financial actions by default, and a read-only model-gateway
credential boundary without action credentials.

A fresh Compose project named `reclaim-t125` was started with the merged test
configuration for `postgres`, `redis`, and `minio` only. All three containers
reported healthy. The observed images were PostgreSQL 16.6-alpine, Redis
7.4.1-alpine, and MinIO `RELEASE.2024-12-18T13-15-44Z`. That isolated project
was then removed with its own containers, volume, and network.

The full 21-service stack was not started: the application services reference
external GHCR images that were not available locally. No hosted service health
or full-stack smoke result is claimed.

## Canonical quickstart flow

The canonical fixture `tests/fixtures/canonical/incident.json` was replayed with
fixture version `canonical-v1.0.0` and deterministic seed
`canonical-seed-001`. Two independent runs compared equal.

Observed result:

- Mode and label: `replay`.
- `side_effects`: `false`.
- Remote side effects: empty.
- Terminal state: `escalated_unresolved`.
- Audit records: 13, each carrying the fixture tenant and case identifiers.
- Attribution included `malicious`, `legitimate`, and `uncertain` labels.
- Exposure currency: INR; gross, recoverable, and contained value were each
  30,000 minor units; legitimate value disrupted was 0; remaining exposure was
  0.
- Policy result: `approval_required`.
- Approval status: `approved`, with separation of duties true.
- Action: simulation only.
- Unknown-result path: reconciled before retry.
- Verification: inconclusive for the approval-gated action.
- Escalation owner: present.

All expected canonical stage outcomes were present and truthy: incident
accepted, evidence collected, timeline converged, attribution completed,
exposure calculated, proposal validated, policy approval required, approval
approval required, action simulated with no side effect, reconciliation before
retry reconciled, verification inconclusive for the gated action, escalation
required, and terminal escalated unresolved.

## Replay/live truth and variants

An explicit `live` request against the unqualified local environment was
observed to fall back to `replay`. The requested mode remained `live`, while
effective and final modes were `replay`; the fallback reason was populated,
`live_execution_occurred` was false, and side effects were false. No live
provider, connector, merchant, or financial action was executed.

All 21 required variants were exercised in replay mode. Every result was
replay-labelled, had `side_effects: false`, and had no remote side effects:

| Variant | Observed outcome |
|---|---|
| `approval_expired` | `expired` |
| `approval_gating` | `approval_required` |
| `approval_rejected` | `rejected` |
| `approval_required` | `approval_required` |
| `duplicate_action_attempt` | `duplicate` |
| `duplicate_delivery` | Non-empty variant result; side-effect-free replay |
| `duplicate_events` | Non-empty variant result; side-effect-free replay |
| `escalation` | `escalated_unresolved` |
| `forbidden_proposal` | `rejected` |
| `inconclusive_verification` | `escalated_unresolved` |
| `invalid_signature` | `quarantined` |
| `missing_evidence` | `escalated_unresolved` |
| `model_unavailability` | `replay` |
| `out_of_order_events` | `converged` |
| `partial_unavailable_evidence` | `escalated_unresolved` |
| `policy_denial` | `denied` |
| `provider_unavailability` | `replay` |
| `reconciliation_before_retry` | `reconciled` |
| `replay_fallback` | `replay` |
| `unknown_remote_result` | `reconciled` |
| `verification_failure` | `verified_failed` |

The duplicate-delivery and duplicate-events assertions require a non-empty
outcome but do not assign a stronger semantic label in the acceptance test;
their replay results were still observed to be side-effect-free.

## Projection rebuild

The Neo4j projection test used a deterministic fake driver. Two events were
applied in occurred-at/event-id order during rebuild, with `applied_events: 2`
and `deleted_nodes: 2`. A mixed-tenant rebuild was rejected with the expected
tenant-boundary error.

The live Neo4j checks were skipped because
`RECLAIM_NEO4J_URI`, `RECLAIM_NEO4J_USER`, and `RECLAIM_NEO4J_PASSWORD` were not
configured. No live Neo4j result is claimed.

## Evaluation metadata and held-out controls

The observed evaluation manifest reported:

- Manifest version: `evaluation-manifest-v1.0.0`.
- Corpus version: `fs001-local-empty-v1.0.0`.
- Actual cases: 0; target cases: 500.
- Actual development/validation/held-out counts: 0/0/0.
- `assignments_frozen_before_overlay: true`.
- `held_out_sealed: true`.
- Available source cases and generated overlay cases: 0/0.
- Environment: `local-unqualified`.

The T125 test also ran the evaluation harness against three in-memory
development cases to verify actual sample-size, provenance, confidence
interval, integer minor-unit, and non-production markers. That three-case
execution is a control test, not a benchmark corpus or production metric.

The sealed-store control denied a `model_selection` read and allowed a read
only after explicit final-evaluation authorization. No held-out payload was
exposed.

## Observability and reviewer traceability

The observed evaluation trace preserved tenant, case, correlation, evaluation
run, and metric-report references; marked itself non-authoritative; and carried
replay/no-side-effect truth. Raw evidence, prompts, and credentials were
absent. The static dashboard checks observed a non-editable Grafana dashboard
with replay, resolution, precision/recall, latency, forbidden-action, and
provenance panels. Langfuse and MLflow configs were observed disabled,
non-authoritative, and configured not to retain raw evidence or held-out
payloads.

The hosted Grafana, Prometheus, Loki, Langfuse, and MLflow endpoints were not
started in this environment. The result is configuration and redaction
evidence, not a live observability dashboard claim.

The operator/reviewer UI was exercised in the in-app browser against a local
Next.js instance using a temporary deterministic read-model stub. The observed
workflow rendered the canonical tenant/case, replay simulation notice, timeline
filters, technical-chain expansion, exposure, policy, approval, action,
verification, escalation, terminal, and audit views. The simulated replay
control produced a recorded replay result with terminal
`escalated_unresolved` and no remote side effects. Browser console error and
warning logs were empty for this interaction. No live API integration, live
approval submission, live escalation submission, or merchant action was
claimed.

## Safety and boundary observations

The canonical replay and all variant smoke runs observed no remote side
effects. The approval, idempotency, reconciliation, verification, forbidden-
proposal, tenant-authorization, and recovery regression checks passed where
their local deterministic fixtures were available. No forbidden execution was
observed in these replay/acceptance checks, and the canonical terminal state
was one of the allowed terminal states.

The full available Python run skipped environment-gated live checks for
PostgreSQL, fresh migrations, non-owner RLS, Temporal, Redpanda, Neo4j, MinIO,
Vault, model-analysis persistence, US1 live services, and merchant/provider
connectors. The explicit migration/RLS command reported 5 passed and 14
skipped for those missing URLs. These skips are limitations, not successful
live validations.

No performance baseline was rerun by T125; the existing
`docs/validation/performance-baseline.md` remains a separate local no-op
baseline and is not presented here as intake, replay, or release-SLO evidence.

## T125 conclusion

The T125 acceptance gate passed for the available local deterministic and
configuration-qualified checks. T125 is the only task closed by this evidence;
T126 and all later Phase 7 tasks remain unstarted.
