# Implementation Plan: Incident Intake to Verified Containment

**Branch**: `main` (feature context: `001-incident-intake-containment`) | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)

**Input**: Approved and clarified feature specification from `specs/001-incident-intake-containment/spec.md`

## Summary

FS-001 is a complete tenant-ready incident response vertical slice. The design separates deterministic case, evidence, timeline, financial, policy, gateway, verification, and audit logic from model inference. A Temporal workflow coordinates durable progress and recovery; PostgreSQL owns business state; Redpanda transports versioned domain events; Neo4j is a rebuildable relationship projection; MinIO retains raw evidence and artifacts; Redis is limited to bounded coordination; and all external side effects pass through the isolated Action Gateway.

The implementation sequence is dependency-ordered: establish contracts and tenant/security foundations, ingest and persist incidents, collect and normalize evidence, reconstruct the deterministic timeline, attribute and calculate exposure, generate bounded proposals, evaluate policy and approvals, execute/reconcile/verify actions, then add replay/evaluation and the complete demonstration topology. Every slice is independently testable and preserves the full architecture.

## Technical Context

**Language/Version**: TypeScript for the Next.js web application and Python for FastAPI services, Temporal workers, deterministic domain services, and model/attribution adapters. Exact patch versions are pinned in implementation lockfiles before coding.

**Primary Dependencies**: Next.js/TypeScript, FastAPI/Pydantic, Temporal Python SDK, LangGraph, LiteLLM, LightGBM, PostgreSQL client/driver, Redis client, Redpanda-compatible Kafka client, Neo4j driver, MinIO client, Keycloak/OIDC, Vault, OpenTelemetry, Prometheus/Grafana/Loki, Langfuse, MLflow, Docker Compose, and GitHub Actions.

**Storage**: PostgreSQL is authoritative for tenant, incident, case, evidence metadata, timeline facts, attribution, exposure, policy, approval, action, verification, escalation, audit, outbox, inbox, replay, and evaluation metadata. MinIO stores raw evidence and artifacts with checksums. Neo4j stores a rebuildable relationship projection. Redis stores only bounded cache/lock/rate-limit/coordination data.

**Testing**: Python unit and property tests, TypeScript unit tests, contract tests for every boundary, PostgreSQL/Redpanda/Temporal integration tests, connector simulator tests, failure-recovery tests, security/tenant-isolation tests, browser acceptance tests, and sealed replay/evaluation tests. Test tooling is selected and pinned during implementation without changing the contracts in this plan.

**Target Platform**: Docker Compose on a developer or CI host, with Docker Desktop or Linux Docker Engine. Kubernetes/KServe are future scale-out paths and are not required for this slice.

**Project Type**: Multi-service web application with a Next.js operator UI, FastAPI APIs, durable Temporal workflows, event consumers/projections, connector adapters/simulators, model/attribution services, and an isolated action boundary.

**Performance Goals**: Provisional targets only: p95 deterministic-simulator intake acknowledgement <=2 seconds and canonical replay completion <=5 minutes. Actual p50/p95 latency, throughput, recovery time, and failure rates must be measured on a documented environment before any release threshold or operational claim is adopted.

**Constraints**: One demo merchant with tenant-ready contracts; Razorpay Test Mode only; strict original-payload webhook verification and tenant-scoped event idempotency; no production financial execution by default; no agent side-effect credentials; policy-owned immutable thresholds; separation of duties; explicit terminal states `verified_contained`, `verified_failed`, and `escalated_unresolved`; no generic successful close; no arbitrary network or attacker interaction.

**Scale/Scope**: One complete incident flow and deterministic failure variants for the first demonstration; benchmark target of at least 500 cases when feasible, with a 60% development, 20% validation, and 20% sealed held-out split acceptable. Target at least 100 held-out cases, preferably 150 or more, while never fabricating or padding cases. Splits must be leakage-safe across entity/customer and time before synthetic overlay generation, maintain at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases, keep held-out seeds/scenarios inaccessible to prompts/tuning/model selection, and report confidence intervals with evaluation metrics. The design must not hard-code a one-merchant data model.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

### Pre-design gate

- **I. Defense-Only Operation**: PASS. Connectors are merchant-controlled and allowlisted; forbidden attacker interaction, probing, arbitrary access, and unauthorized network behavior are out of scope and rejected.
- **II. Harnessed Agent and Action Gateway**: PASS. The model boundary produces typed analysis/proposals only. The Action Gateway is the sole side-effect boundary.
- **III. Deterministic Financial Integrity**: PASS. Exposure and refund eligibility are trusted deterministic calculations in integer minor units and explicit currency.
- **IV. Authoritative State and Durable Workflows**: PASS. PostgreSQL owns business state and Temporal owns durable orchestration; Redis is non-authoritative.
- **V. Event and Projection Ownership**: PASS. Redpanda is transport with outbox/inbox handling; Neo4j is rebuildable; MinIO retains raw evidence.
- **VI. Policy, Approval, Idempotency, and Verification**: PASS. Versioned policy, approval, stable idempotency, reconciliation-before-retry, and verified terminal outcomes are required.
- **VII. Tenant Isolation, Least Privilege, and Untrusted Evidence**: PASS. Tenant scope is carried through every contract; evidence is untrusted; secrets are scoped and PII is minimized.
- **VIII. Interchangeable Models and Fair Evaluation**: PASS. Provider-neutral model contracts, identical case/tool/policy inputs, and grouped sealed evaluation are specified.
- **IX. Honest Metrics and Reproducible Audit**: PASS. Required metrics, provenance, replay labeling, and append-only audit are included; no result is claimed before measurement.
- **X. Test-First Delivery and Explicit Architecture Decisions**: PASS. The plan includes all relevant test classes and ADRs for authority, action safety, and replay/evaluation.

No constitution violation or complexity exception is required.

## Architecture and Service Boundaries

| Boundary | Owns | Reads | Writes / side effects |
|---|---|---|---|
| Next.js operator UI | Case review, approvals, replay/evaluation views | API read models and audit views | Submits typed intake, approval, replay, and escalation decisions through APIs |
| Intake API | Incident requests, Razorpay Test Mode webhook verification, case creation command validation | Tenant/connector configuration | PostgreSQL incident/case/outbox; no remote merchant mutation |
| Evidence orchestrator/adapters | Connector invocation and evidence provenance | Case and connector scope | PostgreSQL evidence metadata; MinIO raw objects; emits evidence events |
| Deterministic domain services | Deduplication, ordering, attribution aggregation, exposure, proposal validation, policy evaluation | PostgreSQL facts and versioned policy/model outputs | PostgreSQL derived facts and audit; no external side effects |
| Temporal workflow worker | Durable orchestration, retries, timers, signals, recovery, compensation/escalation routing | PostgreSQL state and event status | Workflow state and commands to activities; does not become business state |
| Model gateway | Provider-neutral structured inference and model/provider metadata | Redacted case representation and approved tools | Typed analysis output and model audit metadata; no action credentials |
| Action Gateway | Allowlisted side-effect execution, idempotency, reconciliation, verification dispatch | Approved proposals, approvals, connector action scope | Merchant-controlled mutations only through isolated adapters; execution/audit records |
| Event transport/consumers | Versioned event delivery and inbox/outbox processing | PostgreSQL outbox | Redpanda topics; projection consumers; no authoritative business decisions |
| Neo4j projection | Relationship queries for case exploration | Versioned domain events | Rebuildable graph only; never required for correctness |
| Observability stack | Traces, metrics, logs, model traces/evaluation metadata | Redacted telemetry | OpenTelemetry, Prometheus, Grafana, Loki, Langfuse, MLflow with tenant/case correlation |

### State ownership

- PostgreSQL is the source of truth for all business state, policy versions, approvals, action executions, verification, escalation, audit, and replay/evaluation metadata.
- Temporal owns workflow execution history, durable retries, timers, signals, and recovery state, but workflow activities must read/write authoritative business state through explicit repositories/commands.
- Redpanda carries versioned asynchronous events from transactional outbox to inbox consumers. Consumer offsets are not business completion.
- Neo4j is rebuilt from PostgreSQL-backed events and may be deleted/recreated without loss of correctness.
- Redis is optional coordination/cache/rate limiting only; no financial or terminal-state decision depends solely on it.
- MinIO stores immutable raw evidence/artifacts; searchable normalized facts and their provenance remain in PostgreSQL.

### End-to-end event flow

1. An authenticated merchant/operator or validated Razorpay Test Mode webhook reaches the Intake API.
2. The API validates tenant and connector scope, verifies the original webhook payload where applicable, enforces `(tenant, connector, provider_event_id)` idempotency, and persists the incident/case and outbox record transactionally.
3. Temporal starts or signals the case workflow. Evidence activities call only approved connector contracts and persist raw evidence checksums plus normalized metadata.
4. Deterministic services deduplicate and order timeline events, combine rules/LightGBM attribution evidence, and calculate financial exposure.
5. The bounded model gateway receives redacted structured case data and returns typed attribution/proposal output. The model has no side-effect credentials or unrestricted tools.
6. Deterministic proposal validation and versioned policy evaluation produce allow, deny, approval-required, or escalate decisions. Every decision is persisted and emitted as a versioned event.
7. Policy-permitted reversible actions or separately approved high-impact actions are sent to the Action Gateway with stable idempotency keys.
8. The Action Gateway executes through an allowlisted merchant connector, reconciles unknown results before retry, verifies resulting state, and records verified success, verified failure, or escalation.
9. Consumers update rebuildable projections and redacted observability stores. The append-only audit trail links every input, decision, version, approval, remote result, and outcome.

## Dependency-Ordered Vertical Slices

### Slice 0 - Contracts, tenancy, identity, and audit foundation

Define versioned schemas, tenant context propagation, Keycloak/OIDC roles, Vault secret scopes, PostgreSQL repository boundaries, audit envelope, transactional outbox/inbox, and the connector/action contract registry. Establish forbidden-tool tests and redaction rules before any model or side-effect path exists.

### Slice 1 - Incident intake and case creation

Implement authenticated incident intake, stable correlation identity, tenant-aware case creation, idempotent duplicate intake, and Temporal workflow start/signal. Add Razorpay Test Mode webhook verification as a connector-specific implementation of the signed original-payload contract, with raw payload checksum and quarantine behavior.

### Slice 2 - Evidence collection and deterministic timeline

Implement read-only approved connectors and matching simulators for sessions, devices, profile changes, orders, fulfillment, and payments. Persist provenance and raw objects, normalize facts, deduplicate, order with documented timestamp precedence, and expose missing/partial/stale evidence without inference.

### Slice 3 - Attribution and deterministic financial exposure

Implement rules and LightGBM adapter contracts, preserve versioned advisory outputs, support malicious/legitimate/uncertain labels, and calculate exposure from trusted captured-payment facts in minor currency units. Add invariant/property tests for duplicate events, reimbursement bounds, currency, and legitimate value disruption.

### Slice 4 - Bounded analysis, typed proposals, policy, and approvals

Implement provider-neutral LangGraph/LiteLLM boundary, redaction, typed proposal schemas, allowlist validation, immutable policy versions, centrally bounded tenant configuration, approval separation of duties, and explicit policy audit. Model output cannot mutate policy or execute a side effect.

### Slice 5 - Action Gateway, reconciliation, verification, and escalation

Implement isolated gateway adapters for suspicious-session revocation and eligible fulfillment holds, with approval-gated cancellation/refund/identity restoration contracts present but live financial execution disabled by default. Add stable action idempotency, unknown-result reconciliation, verification, escalation ownership, and terminal case states.

### Slice 6 - Replay, evaluation, observability, and demonstration

Create the canonical end-to-end fixture and deterministic variants, labeled live/replay mode, leakage-safe entity/customer and temporal split validation before synthetic overlays, grouped 60/20/20 evaluation metadata, a benchmark target of at least 500 cases when feasible, and at least 100 held-out cases (preferably 150 or more). Enforce at least 25% no-compromise/false-alert cases, mixed legitimate/malicious activity in at least 30% of compromised cases, sealed held-out seeds/scenarios inaccessible to prompts/tuning/model selection, confidence intervals, metric provenance, dashboards/traces/logs, and the full Docker Compose validation flow. Measure provisional performance targets; do not turn them into release thresholds without baselines.

## Testing Strategy

- **Unit/property**: monetary arithmetic, exposure invariants, ordering/tie-breaking, deduplication, tenant scope, policy thresholds, idempotency key derivation, terminal-state transitions, redaction, and proposal schemas.
- **Contract**: intake/webhook, evidence connector, simulator, event envelope, model gateway, policy decision, approval, Action Gateway, verification, audit, replay, and evaluation metadata contracts.
- **Integration**: PostgreSQL authority, transactional outbox/inbox, Redpanda delivery, Temporal restart/retry/signal behavior, MinIO checksums, Neo4j rebuild, Redis non-authority, Keycloak/Vault scopes, and OpenTelemetry correlation.
- **Failure recovery**: duplicate/out-of-order events, unavailable/partial/stale connectors, invalid signatures, process restart, timeout, unknown remote result, reconciliation-before-retry, stale policy version, verification ambiguity, and escalation.
- **Security**: cross-tenant access attempts, untrusted prompt/evidence injection, forbidden action proposals, missing/overbroad credentials, arbitrary network/tool access, PII leakage, approval self-dealing, and audit tampering.
- **Acceptance/E2E**: mixed legitimate/attacker canonical incident from intake through verified containment or escalation, including the complete Compose topology and reviewer traceability.
- **Evaluation**: benchmark target of at least 500 cases when feasible; acceptable 60/20/20 development/validation/sealed-held-out split; at least 100 held-out cases targeted, preferably 150 or more; leakage-safe entity/customer and temporal separation before synthetic overlay generation; at least 25% no-compromise/false-alert cases; mixed legitimate/malicious activity in at least 30% of compromised cases; held-out seeds/scenarios inaccessible to prompts, tuning, and model selection; confidence intervals alongside malicious-action precision/recall, contained value, legitimate value disrupted, resolution success, latency, tool efficiency, forbidden attempts/executions, and model cost. Do not fabricate or pad cases; report actual sample size and statistical limitations.

## Deployment Topology

The authoritative initial deployment is one Docker Compose project containing:

- `web`: Next.js operator interface.
- `api`: FastAPI intake/case/approval/replay API.
- `workflow-worker`: Temporal Python worker and activities.
- `model-gateway`: provider-neutral LangGraph/LiteLLM adapter with redacted inputs and no side-effect credentials.
- `attribution`: deterministic rules/LightGBM adapter service.
- `evidence-connectors`: approved merchant-controlled read adapters and deterministic simulators.
- `action-gateway`: isolated allowlisted action/reconciliation/verification service with narrowly scoped connector credentials.
- `postgres`: authoritative business state, policies, approvals, action state, audit, outbox/inbox, replay/evaluation metadata.
- `temporal`: Temporal server plus its required persistence configuration.
- `redpanda`: event transport and versioned topic infrastructure.
- `neo4j`: rebuildable relationship projection.
- `minio`: raw evidence and artifact storage with checksum verification.
- `redis`: bounded cache, locks, rate limiting, and coordination only.
- `keycloak`: OIDC identity and role issuance.
- `vault`: scoped secret management.
- `otel-collector`, `prometheus`, `grafana`, `loki`: traces, metrics, dashboards, and logs.
- `langfuse`, `mlflow`: redacted model traces and evaluation/model metadata.

Compose networking must separate public ingress, application services, data services, and the Action Gateway egress boundary. Only the API/UI ingress is externally exposed for the demo; databases and gateway administration remain internal. Production-like credential, network, and policy defaults must keep live financial actions disabled.

## Material Decisions and ADRs

The following decisions are recorded in feature-local ADRs and must be reviewed with the plan:

- ADR-001: authoritative ownership and event/projection boundaries.
- ADR-002: agent/action safety boundary and isolated Action Gateway.
- ADR-003: deterministic replay, grouped evaluation, and honest performance baselines.

## Phase 1 Design Artifacts

- [research.md](./research.md) records the planning decisions, rationale, alternatives, and unresolved implementation validation items.
- [data-model.md](./data-model.md) defines authoritative entities, relationships, invariants, and state transitions.
- [contracts/](./contracts/) defines boundary contracts without implementation bodies.
- [quickstart.md](./quickstart.md) defines the future Compose validation flow and expected evidence.
- [decisions/](./decisions/) records material architectural decisions.

## Constitution Check (Post-design)

- **Architecture ownership**: PASS. PostgreSQL, Temporal, Redpanda, Neo4j, Redis, MinIO, and the complete Compose topology retain their approved roles.
- **Defense and side effects**: PASS. All connectors are allowlisted and merchant-controlled; the model has typed proposal authority only; the Action Gateway is isolated and idempotent.
- **Financial safety**: PASS. Trusted integer-minor-unit calculations, captured-payment/refund bounds, approval gates, reconciliation, and verification are explicit.
- **Tenant/security boundary**: PASS. Tenant scope, OIDC/Vault least privilege, untrusted evidence, redaction, and cross-tenant tests are planned.
- **Model/evaluation integrity**: PASS. Providers share one interface and sealed grouped evaluation; replay and synthetic/hybrid results are labeled; metrics are not fabricated.
- **Audit/test/decision governance**: PASS. Append-only audit, required test classes, ADRs, and baseline-before-threshold rules are included.

No gate violations remain. `tasks.md` is intentionally not created by this planning phase.

## Complexity Tracking

No constitution violations or unjustified complexity exceptions.
