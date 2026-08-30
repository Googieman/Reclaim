---

description: "Dependency-ordered implementation tasks for FS-001"
---

# Tasks: Incident Intake to Verified Containment

**Input**: `specs/001-incident-intake-containment/spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `decisions/`, and `quickstart.md`

**Architecture baseline**: PostgreSQL is authoritative for business state; Temporal owns durable workflow state; Redpanda transports versioned events through transactional outbox/inbox; Neo4j is rebuildable; MinIO stores immutable evidence/artifacts; Redis is bounded coordination only; Keycloak/OIDC and Vault provide scoped identity/secrets; the model emits typed proposals only; the isolated Action Gateway is the sole side-effect boundary.

**Testing policy**: Tests are included because FS-001 and the RECLAIM constitution require unit/property, contract, integration, failure-recovery, security, acceptance, and evaluation validation. Tests for each slice are listed before the implementation tasks they validate.

**Path convention**: Planned Python services live under `backend/`, the Next.js application under `frontend/`, shared contracts under `packages/contracts/`, deployment under `infra/`, and cross-service tests under `tests/`. These paths are implementation targets; this task phase creates no application code.

## Phase 1: Setup — project initialization

**Purpose**: Establish the multi-service repository structure, pinned tooling, and local configuration surfaces without implementing business behavior.

- [X] T001 Create the planned service/package directory layout in `backend/`, `frontend/`, `packages/contracts/`, `infra/`, `tests/`, `scripts/`, and `docs/architecture/` according to `specs/001-incident-intake-containment/plan.md`.
- [X] T002 Pin Python, TypeScript, and infrastructure dependency versions in `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json`, and `infra/versions.env` without changing the approved component list.
- [X] T003 Define typed environment/configuration schemas and non-secret examples in `backend/app/config.py`, `frontend/src/lib/config.ts`, and `infra/.env.example`; include tenant, provider mode, live-action-disabled, and replay labels.
- [X] T004 Configure Python, TypeScript, contract, integration, browser, and property-test runners in `backend/pyproject.toml`, `frontend/package.json`, `tests/pytest.ini`, and `frontend/vitest.config.ts`.
- [X] T005 Configure formatting, linting, type checking, and import-boundary checks in `backend/pyproject.toml`, `frontend/package.json`, `.pre-commit-config.yaml`, and `scripts/check_boundaries.ps1`.
- [X] T006 Record the approved FS-001 ownership and side-effect boundaries in `docs/architecture/fs-001-boundaries.md`, linking ADR-001, ADR-002, ADR-003, and the source artifacts under `specs/001-incident-intake-containment/`.
- [X] T007 Add deterministic fixture and test-data loading conventions in `tests/fixtures/README.md`, `tests/fixtures/seeds/README.md`, and `scripts/fixtures/README.md`; prohibit secrets and unsealed held-out data from the repository.
- [X] T008 Add version/commit provenance capture for builds and test runs in `scripts/build_provenance.py`, `backend/app/provenance.py`, and `frontend/src/lib/provenance.ts`.

**Checkpoint**: Tooling and path conventions are established; no task in this phase grants a model or service side-effect authority.

---

## Phase 2: Foundational — contracts, state ownership, security, and platform boundaries

**Purpose**: Complete the blocking platform and contract foundations before any user-story slice. No user-story task may be marked complete until these foundations pass their contract and isolation tests.

### Versioned boundary contracts

- [X] T009 Define generated/shared schema ownership and versioning rules in `packages/contracts/README.md` and `packages/contracts/schema_registry.py`, preserving tenant and correlation fields on every request, event, decision, tool call, and audit record.
- [X] T010 Encode incident intake and Razorpay webhook request/response schemas in `packages/contracts/intake.py` from `specs/001-incident-intake-containment/contracts/intake-webhook.md`, including accepted, duplicate, rejected, and quarantined outcomes.
- [X] T011 Encode connector manifests and evidence/action request-response schemas in `packages/contracts/connectors.py` from `specs/001-incident-intake-containment/contracts/connectors.md`, including tenant scope, resource/operation allowlists, auth scope, limits, timestamps, idempotency, and all declared failure states.
- [X] T012 Encode the versioned event envelope and event-family schemas in `packages/contracts/events.py` from `specs/001-incident-intake-containment/contracts/events.md`, including checksums, causation, correlation, and producer identity.
- [X] T013 Encode model analysis, typed proposal, deterministic policy decision, and approval schemas in `packages/contracts/analysis_policy.py` from `specs/001-incident-intake-containment/contracts/analysis-policy.md`.
- [X] T014 Encode Action Gateway request, state, response, and verification schemas in `packages/contracts/action_gateway.py` from `specs/001-incident-intake-containment/contracts/action-gateway.md`; make `unknown` a first-class state.
- [X] T015 Encode append-only audit, replay, and evaluation metadata schemas in `packages/contracts/audit_replay.py` from `specs/001-incident-intake-containment/contracts/audit-replay.md`.
- [X] T017 Add contract tests for every boundary in `tests/contract/test_intake.py`, `tests/contract/test_webhook.py`, `tests/contract/test_connectors.py`, `tests/contract/test_events.py`, `tests/contract/test_analysis_policy.py`, `tests/contract/test_action_gateway.py`, and `tests/contract/test_audit_replay.py`; run these boundary tests before the dependent registry service implementation.
- [X] T016 Implement the connector/action contract registry and compatibility checks in `backend/app/contracts/registry.py` and `backend/tests/contract/test_contract_registry.py`; reject manifests with missing tenant scope, overbroad operations, missing auth scope, or incompatible versions, after T017 boundary tests pass.

### Authoritative PostgreSQL state and audit chain

- [X] T018 Create migrations for tenant-ready authoritative entities in `backend/db/migrations/001_authoritative_entities.sql`, covering tenants, incidents, cases, connector configurations, evidence, timeline events, attribution, financial exposure, policy, approvals, actions, verification, escalation, replay, and evaluation metadata from `specs/001-incident-intake-containment/data-model.md`.
- [X] T019 Add tenant context, row-level isolation policies, and tenant-scoped uniqueness constraints in `backend/db/migrations/002_tenant_isolation.sql` and `backend/app/db/tenant_context.py`; enforce `(tenant_id, connector_id, provider_event_id)` webhook identity separately from action idempotency.
- [X] T020 Implement explicit PostgreSQL repositories and transaction boundaries in `backend/app/db/repositories/` and `backend/app/db/unit_of_work.py`; ensure all business-state, policy, approval, action, verification, escalation, and audit writes are authoritative database writes.
- [X] T021 Implement the append-only, checksum-linked audit chain in `backend/app/audit/chain.py` and `backend/tests/unit/test_audit_chain.py`; record tenant/case, actor, evidence/input references, policy/model/provider/approval/execution versions, correlation IDs, outcome, previous linkage, and no secrets or unnecessary PII.
- [X] T022 Implement PostgreSQL transactional outbox writes in `backend/app/events/outbox.py` and `backend/tests/integration/test_outbox_transaction.py`; require business state and its outbox record to commit atomically.
- [X] T023 Implement the tenant-aware PostgreSQL inbox/idempotency store in `backend/app/events/inbox.py` and `backend/tests/integration/test_inbox_idempotency.py`; consumer offsets must not represent business completion.

### Durable workflow and event transport

- [X] T024 Define Temporal workflow IDs, activities, retry policies, timers, signals, and recovery commands in `backend/workflows/case_workflow.py` and `backend/workflows/commands.py`, while keeping business truth in PostgreSQL.
- [X] T025 Add Temporal/PostgreSQL restart, retry, and signal integration tests in `tests/integration/test_temporal_authority_split.py`; verify workflow history can recover without bypassing repository validation.
- [X] T026 Implement Redpanda topic/version configuration, outbox publisher, inbox consumer dispatch, and delivery acknowledgements in `backend/app/events/redpanda.py` and `infra/redpanda/topics.yaml`; cover at-least-once delivery and out-of-order handling.

### Storage, coordination, identity, and secret boundaries

- [X] T027 Implement the rebuildable Neo4j projection bootstrap/replay boundary in `backend/projections/neo4j_projection.py` and `backend/tests/integration/test_neo4j_rebuild.py`; projection loss must not alter PostgreSQL correctness.
- [X] T028 Implement immutable MinIO evidence/artifact object storage with checksum verification in `backend/app/storage/minio_evidence.py` and `backend/tests/integration/test_minio_checksums.py`; normalized searchable facts remain in PostgreSQL.
- [X] T029 Implement Redis-backed bounded cache, lock, rate-limit, and coordination helpers in `backend/app/coordination/redis.py` and `backend/tests/integration/test_redis_non_authority.py`; no terminal, financial, policy, or action decision may depend solely on Redis.
- [X] T030 Configure Keycloak/OIDC tenant-aware roles and API verification in `infra/keycloak/realm-reclaim.json`, `backend/app/auth/oidc.py`, and `backend/tests/security/test_oidc_tenant_roles.py`; distinguish reviewer, approver, escalation-owner, policy-owner, and service identities.
- [X] T031 Configure Vault secret paths, tenant scoping, service policies, rotation references, and Action Gateway-only action credentials in `infra/vault/policies/` and `backend/app/secrets/vault.py`; verify model/workflow/UI identities cannot read side-effect credentials.
- [X] T032 Establish redacted OpenTelemetry correlation, metrics, logs, model traces, and evaluation metadata sinks in `backend/app/observability/`, `infra/observability/otel-collector.yaml`, `infra/observability/prometheus.yml`, `infra/observability/loki.yml`, `infra/observability/grafana/`, `infra/langfuse/`, and `infra/mlflow/`.

### Foundational control plane and security tests

- [X] T033 Implement the tenant-scoped connector registry, policy-owner registry, role registry, and configuration-boundary interfaces in `backend/app/control_plane/registry.py` and `backend/app/control_plane/tenant_config.py`; this registry must expose declarations, not unrestricted runtime capabilities.
- [X] T034 Add forbidden-tool, arbitrary-network, credential-probing, untrusted-evidence, PII-redaction, and cross-tenant boundary tests in `tests/security/test_forbidden_capabilities.py`, `tests/security/test_untrusted_evidence.py`, `tests/security/test_pii_redaction.py`, and `tests/security/test_cross_tenant_isolation.py`.
- [X] T035 Run the foundational integration gate in `tests/integration/test_foundation_gate.py`, covering PostgreSQL authority, Temporal separation, Redpanda outbox/inbox, Neo4j rebuildability, MinIO checksums, Redis non-authority, Keycloak/OIDC scopes, Vault scopes, audit append-only behavior, and redacted telemetry.

**Checkpoint**: Shared contracts, tenant/security foundations, authoritative storage, workflow/event ownership, storage/identity boundaries, and audit are testable before story work begins.

### Post-T035 Foundation Security Remediation

- [X] SR-001 Remediate tenant-role binding so verified OIDC authorization binds subject, tenant membership, and roles; derive the PostgreSQL UoW/repository tenant context only from the authenticated single-tenant context; add adversarial cross-tenant authorization coverage. Validated with focused authorization/UoW tests and the default full Python suite on 2026-08-30. No contract or ADR was changed.
- T036–T042 are unblocked by the accepted SR-001 remediation; the current US1 test batch is marked complete below.

---

## Phase 3: User Story 1 — Intake and reconstruct an incident (Priority: P1) — MVP vertical slice

**Goal**: Accept one tenant-scoped incident, authenticate/quarantine applicable Razorpay Test Mode webhooks, collect approved merchant evidence, and produce a deterministic provenance-linked timeline.

**Independent Test**: Submit the canonical mixed legitimate/attacker fixture with duplicate and out-of-order events and verify one tenant-scoped case, deterministic deduplicated timeline, raw evidence checksums, quarantine behavior, and no unapproved side effect.

### Tests for User Story 1

- [X] T036 [P] [US1] Add incident intake contract and API validation tests in `tests/contract/test_incident_intake.py` for tenant identity, source, receipt time, reporter context, stable correlation identity, duplicate acknowledgement, rejection, and quarantine.
- [X] T037 [P] [US1] Add Razorpay Test Mode original-payload authenticity, required-provider-event-ID, checksum, tenant mismatch, invalid signature, incomplete payload, and duplicate-delivery tests in `tests/contract/test_razorpay_webhook.py`.
- [X] T038 [P] [US1] Add property tests for duplicate and out-of-order convergence in `tests/property/test_timeline_convergence.py`; repeated runs must yield identical business facts, timeline ordering, and no duplicate financial/action facts.
- [X] T039 [P] [US1] Add evidence connector and deterministic simulator contract tests in `tests/contract/test_evidence_connectors.py` for sessions, devices, profile changes, orders, fulfillment, and payments plus partial, stale, unavailable, duplicate, out-of-order, timeout, and invalid states.
- [X] T040 [P] [US1] Add raw-object checksum and normalized-provenance integration tests in `tests/integration/test_evidence_provenance.py` using `tests/fixtures/evidence/` and `infra/minio/`.
- [X] T041 [P] [US1] Add deterministic timestamp-precedence, UTC normalization, stable tie-breaking, deduplication, and conflicting-source tests in `tests/unit/test_timeline_reconstruction.py`.
- [X] T042 [P] [US1] Add intake security tests in `tests/security/test_intake_boundaries.py` for cross-tenant webhook isolation, untrusted report instructions, oversized/schema-invalid payloads, and absence of direct remote mutation.
- [ ] T043 [US1] Add the canonical US1 acceptance test in `tests/acceptance/test_intake_to_timeline.py`, asserting the independent-test criteria and explicit success/failure/quarantine outcomes for every stage.

### Intake and Razorpay Test Mode integration

- [ ] T044 [US1] Implement authenticated incident intake commands and case-creation API routes in `backend/api/intake.py`, `backend/app/intake/service.py`, and `backend/tests/integration/test_intake_service.py` for FR-001 and FR-003.
- [ ] T045 [US1] Implement Razorpay Test Mode original-payload verification and event identity handling in `backend/connectors/razorpay/webhook.py` using tenant-scoped Vault references; preserve raw bytes/checksum, quarantine invalid/incomplete events, and acknowledge valid duplicates without downstream reprocessing for FR-002 and FR-007.
- [ ] T046 [US1] Add the configured Razorpay Test Mode connector manifest, provider fixture loader, signature/header configuration, secret-rotation validation seam, and live/replay labeling in `backend/connectors/razorpay/manifest.py`, `tests/fixtures/razorpay/`, and `docs/integrations/razorpay-test-mode.md`; do not claim provider behavior until configuration validation passes.
- [ ] T047 [US1] Implement authoritative incident/case persistence, stable correlation identity, intake status transitions, and duplicate case handling in `backend/app/incidents/service.py`, `backend/app/cases/service.py`, and `backend/app/db/repositories/incidents.py`.
- [ ] T048 [US1] Implement webhook idempotency, quarantine records, raw-payload object references, and audit events in `backend/app/intake/webhook_processing.py`, `backend/app/db/repositories/webhooks.py`, and `backend/app/audit/intake.py`; keep webhook idempotency separate from action idempotency.
- [ ] T049 [US1] Implement the case Temporal workflow start/signal path in `backend/workflows/case_workflow.py`, `backend/workflows/activities/intake.py`, and `backend/api/workflow_commands.py`; workflow progress must not replace PostgreSQL case state.

### Evidence connectors, MinIO, Redpanda, and timeline

- [ ] T050 [US1] Implement versioned read-only evidence connector adapters and allowlist checks in `backend/connectors/evidence/` for sessions, devices, profile changes, orders, fulfillment, and payments, with no attacker-facing or arbitrary-network operation.
- [ ] T051 [P] [US1] Implement deterministic evidence simulators using the same manifests and schemas in `backend/connectors/simulators/evidence.py` and `tests/fixtures/evidence/variants/`; fixtures must cover valid, partial, stale, duplicate, out-of-order, timeout, and unavailable outcomes.
- [ ] T052 [US1] Implement the evidence collection orchestrator and Temporal activities in `backend/evidence/orchestrator.py` and `backend/workflows/activities/evidence.py`; record unavailable and partial sources rather than inventing facts.
- [ ] T053 [US1] Persist immutable raw evidence/artifacts through MinIO and normalized evidence metadata through PostgreSQL in `backend/evidence/storage.py`, `backend/app/storage/minio_evidence.py`, and `backend/app/db/repositories/evidence.py`, including checksum, source, observed/received times, completeness, integrity, and untrusted classification.
- [ ] T054 [US1] Implement evidence normalization and source-reference preservation in `backend/evidence/normalization.py` and `backend/tests/unit/test_evidence_normalization.py`; original timestamps and provider identifiers remain available for audit.
- [ ] T055 [US1] Implement deterministic deduplication, UTC timestamp precedence, stable tie-breaking, and timeline state transitions in `backend/timeline/reconstruct.py`, `backend/timeline/models.py`, and `backend/app/db/repositories/timeline.py`.
- [ ] T056 [US1] Emit `incident.accepted`, `webhook.quarantined`, `evidence.collected`, and `timeline.rebuilt` through PostgreSQL outbox and Redpanda consumers in `backend/app/events/incident_events.py` and `backend/app/events/timeline_events.py`.
- [ ] T057 [US1] Implement the Neo4j case/evidence/timeline projection consumer and replayable projection checkpoint in `backend/projections/neo4j_case_projection.py` and `tests/integration/test_neo4j_case_projection.py`; projection delay/loss must not change authoritative results.
- [ ] T058 [US1] Run the US1 vertical-slice gate in `tests/integration/test_us1_vertical_slice.py` and write expected reviewer evidence to `docs/validation/us1-intake-timeline.md` without presenting simulator output as live production evidence.

**Checkpoint**: US1 is independently demonstrable from intake through deterministic timeline and can be handed to US2 as a tenant-scoped, provenance-linked case.

---

## Phase 4: User Story 2 — Attribute activity and quantify exposure (Priority: P1)

**Goal**: Produce versioned advisory attribution, deterministic financial exposure, and bounded provider-neutral typed proposals without granting the agent side-effect authority.

**Independent Test**: Analyze a mixed-activity prepared case and verify malicious/legitimate/uncertain labels, rules and LightGBM provenance, integer-minor-unit exposure totals, redaction, typed proposals, forbidden-attempt rejection, and zero direct side effects.

### Tests for User Story 2

- [ ] T059 [P] [US2] Add attribution contract tests in `tests/contract/test_attribution.py` for rules and LightGBM outputs, input/version/label/confidence/rationale retention, and distinct malicious/legitimate/uncertain labels.
- [ ] T060 [P] [US2] Add LightGBM baseline fixture and adapter parity tests in `tests/unit/test_lightgbm_baseline.py` and `tests/fixtures/attribution/lightgbm/`; record model/version provenance without claiming production performance.
- [ ] T061 [P] [US2] Add financial property tests in `tests/property/test_exposure_invariants.py` for minor units, explicit currency, captured-only refunds, reimbursement bounds, original payment source, contained value, legitimate value disrupted, irreversible loss, and remaining exposure.
- [ ] T062 [P] [US2] Add uncertainty propagation tests in `tests/unit/test_uncertain_attribution.py`; uncertain events must remain uncertain through proposal and policy inputs and may trigger review/escalation.
- [ ] T063 [P] [US2] Add model-boundary security tests in `tests/security/test_model_gateway_boundary.py` for redaction, no Action Gateway credentials, no database writes, no shell, no arbitrary network, and no direct connector access.
- [ ] T064 [P] [US2] Add typed-proposal and forbidden-operation tests in `tests/contract/test_typed_proposals.py` and `tests/security/test_forbidden_proposals.py`; rejected attempts must be auditable and produce zero remote side effects.
- [ ] T065 [US2] Add the canonical US2 acceptance test in `tests/acceptance/test_attribution_exposure_analysis.py`, asserting the independent-test criteria and deterministic outcome recording.

### Deterministic attribution and exposure

- [ ] T066 [US2] Implement rules-based attribution evidence in `backend/attribution/rules.py` and `backend/attribution/models.py`, retaining inputs, method/version, label, confidence, rationale, and evidence references.
- [ ] T067 [US2] Implement the LightGBM baseline adapter and versioned feature/model manifest in `backend/attribution/lightgbm_adapter.py`, `backend/attribution/lightgbm_manifest.py`, and `tests/fixtures/attribution/`; keep output advisory and interchangeable with rules.
- [ ] T068 [US2] Implement trusted deterministic exposure calculation in `backend/finance/exposure.py` and `backend/app/db/repositories/exposure.py` using integer minor currency units and explicit currency; reject uncaptured, unlinked, fully reimbursed, cross-currency, or unknown-source payment amounts.
- [ ] T069 [US2] Implement attribution aggregation and exposure-source linkage in `backend/analysis/deterministic_summary.py` and `backend/app/db/repositories/attribution.py`; legitimate activity must remain measurable and not silently influence malicious exposure.

### LangGraph/LiteLLM agent harness and typed proposal boundary

- [ ] T070 [US2] Implement structured case redaction and PII minimization in `backend/agent/redaction.py` and `backend/tests/unit/test_agent_redaction.py`; retain evidence references without exposing unnecessary raw data.
- [ ] T071 [US2] Implement the provider-neutral LangGraph analysis graph in `backend/agent/langgraph_harness.py` with bounded state, fixed tool registry, model budget, replay/live label, and typed output checkpoints.
- [ ] T072 [US2] Implement LiteLLM provider adapters and provider/model metadata capture in `backend/agent/litellm_gateway.py` and `backend/agent/providers.py`; all providers receive the same case, tools, policy, budget, and schemas.
- [ ] T073 [US2] Implement read-only evidence and proposal-interface tools in `backend/agent/tools.py` and `backend/agent/tool_registry.py`; explicitly deny payments, refunds, cancellations, account mutations, database writes, shell commands, credential access, arbitrary network, and attacker interaction.
- [ ] T074 [US2] Implement typed analysis response parsing, uncertainty/refusal records, evidence references, token/cost metadata, and typed proposal construction in `backend/agent/output_parser.py` and `backend/agent/proposals.py`; free-form executable instructions are invalid.
- [ ] T075 [US2] Implement deterministic proposal validation against tenant/connector/action allowlists in `backend/analysis/proposal_validator.py` and `backend/tests/unit/test_proposal_validator.py`; scope, target, parameters, currency, amount, and idempotency identity must be bounded before policy evaluation.
- [ ] T076 [US2] Persist model/provider mode, analysis input/output references, refusals, forbidden attempts, and proposal provenance in `backend/app/audit/model_analysis.py` and `backend/app/db/repositories/model_runs.py`.
- [ ] T077 [US2] Implement provider-unavailable deterministic replay fallback in `backend/agent/replay_fallback.py` and `backend/tests/integration/test_model_replay_fallback.py`; label replay and never claim live model execution.
- [ ] T078 [US2] Run the US2 integration gate in `tests/integration/test_us2_analysis_exposure.py`, proving model output cannot bypass deterministic financial/proposal validation or execute a side effect.

**Checkpoint**: US2 produces reproducible advisory analysis and trusted exposure with typed, validated proposals ready for policy; the agent has no side-effect credentials or execution path.

---

## Phase 5: User Story 3 — Contain loss safely and verify the result (Priority: P1)

**Goal**: Evaluate every proposal through immutable deterministic policy and approval controls, execute only through the isolated Action Gateway, reconcile unknown results, verify merchant state, and end in explicit containment, failure, or escalation.

**Independent Test**: Start from a prepared case containing automatic reversible actions, approval-gated actions, duplicate requests, an unknown remote result, inconclusive verification, and unresolved exposure; verify no unsafe execution and explicit terminal outcomes.

### Tests for control plane, policy, approvals, and financial safety

- [ ] T079 [P] [US3] Add policy decision contract tests in `tests/contract/test_policy_decisions.py` for exactly-one results `allow`, `deny`, `approval_required`, or `escalate`, with tenant, permission, confidence, resource state, amount, reversibility, customer impact, approval, policy version, and evaluated conditions.
- [ ] T080 [P] [US3] Add centrally bounded tenant-policy configuration tests in `tests/security/test_policy_bounds.py`; out-of-bound tenant thresholds and model-attempted threshold changes must be denied and audited.
- [ ] T081 [P] [US3] Add approval contract and separation-of-duties tests in `tests/contract/test_approvals.py` and `tests/security/test_approval_separation.py`; cancellation, refund, and identity restoration cannot execute without a valid distinct approver.
- [ ] T082 [P] [US3] Add Action Gateway state-machine contract tests in `tests/contract/test_action_gateway_state.py` for validation, remote result classes, unknown, reconciliation, verification, and escalation transitions.
- [ ] T083 [P] [US3] Add refund and action financial-safety tests in `tests/security/test_refund_safety.py` for captured payment, unreimbursed amount, original source, explicit currency, and live-financial-execution-disabled defaults.
- [ ] T084 [P] [US3] Add idempotency and failure-recovery tests in `tests/integration/test_action_recovery.py` for duplicate requests, process restart, timeout, unknown result, reconciliation-before-retry, and no duplicate non-idempotent remote effect.
- [ ] T085 [P] [US3] Add verification and escalation tests in `tests/integration/test_verification_escalation.py` for verified success, verified failure, inconclusive state, assigned tenant-scoped owner, evidence links, remaining exposure, and human recommendation.
- [ ] T086 [P] [US3] Add terminal-state transition tests in `tests/unit/test_case_terminal_states.py`; permit only `verified_contained`, `verified_failed`, and `escalated_unresolved`, with no generic `closed` state.
- [ ] T087 [US3] Add the canonical US3 acceptance test in `tests/acceptance/test_safe_containment.py`, asserting all safety-critical independent-test conditions and zero forbidden/non-idempotent duplicate actions.

### Deterministic policy and approval control plane

- [ ] T088 [US3] Implement immutable policy versions, checksums, effective intervals, authorized policy-owner publication, and deterministic evaluation in `backend/policy/versions.py`, `backend/policy/evaluator.py`, and `backend/app/db/repositories/policies.py`.
- [ ] T089 [US3] Implement tenant policy configuration within centrally enforced bounds and approved change control in `backend/policy/tenant_configuration.py`, `backend/policy/change_control.py`, and `backend/api/policy.py`; models and ordinary reviewers cannot mutate thresholds at runtime.
- [ ] T090 [US3] Implement approval request, approval, expiry, revocation, and stale-policy re-evaluation workflow in `backend/approvals/service.py`, `backend/api/approvals.py`, and `backend/workflows/activities/approvals.py`; enforce proposer/approver separation.
- [ ] T091 [US3] Persist and emit policy decisions, approval records, denials, escalations, and stale-version re-evaluations in `backend/app/audit/policy.py`, `backend/app/events/policy_events.py`, and `backend/app/db/repositories/policy_decisions.py`.

### Isolated Action Gateway, Razorpay Test Mode, reconciliation, and verification

- [ ] T092 [US3] Implement the isolated Action Gateway service boundary in `backend/action_gateway/service.py`, `backend/action_gateway/validation.py`, and `backend/action_gateway/network_policy.py`; only the gateway may obtain action credentials or invoke merchant-controlled mutations.
- [ ] T093 [US3] Implement allowlisted action connector manifests and deterministic action simulators in `backend/connectors/actions/`, `backend/connectors/simulators/actions.py`, and `tests/fixtures/actions/` for suspicious-session revocation and eligible fulfillment holds, with controlled accepted/rejected/completed/failed/unknown outcomes.
- [ ] T094 [US3] Implement the Razorpay Test Mode payment-action adapter seam in `backend/connectors/razorpay/actions.py` and `docs/integrations/razorpay-test-mode-actions.md`; include captured-payment/original-source validation and keep refund execution disabled by default unless separately configured policy, credentials, approval, and verification are present.
- [ ] T095 [US3] Implement stable action idempotency-key derivation, execution persistence, duplicate response behavior, and unknown-result reconciliation-before-retry in `backend/action_gateway/idempotency.py`, `backend/action_gateway/reconciliation.py`, and `backend/app/db/repositories/action_executions.py`.
- [ ] T096 [US3] Implement merchant-controlled post-action verification in `backend/action_gateway/verification.py` and `backend/app/db/repositories/verifications.py`; inconclusive state is never success and must route to escalation.
- [ ] T097 [US3] Implement tenant-scoped escalation ownership, remaining-exposure capture, evidence links, recommended human decision, and unresolved terminal routing in `backend/escalation/service.py`, `backend/api/escalations.py`, and `backend/app/db/repositories/escalations.py`.
- [ ] T098 [US3] Implement explicit case/action terminal-state transitions and append-only audit/outbox emission in `backend/cases/terminal_states.py`, `backend/app/audit/actions.py`, and `backend/app/events/action_events.py`.
- [ ] T099 [US3] Expose typed policy, approval, escalation, action-status, and audit read/command APIs in `backend/api/control_plane.py` and `backend/api/audit.py`; APIs must not bypass policy, approval, gateway, verification, or tenant checks.
- [ ] T100 [US3] Integrate Temporal activities with policy, approval, Action Gateway, reconciliation, verification, and escalation commands in `backend/workflows/activities/containment.py` and `backend/workflows/case_workflow.py`; durable retries must consult PostgreSQL state.
- [ ] T101 [US3] Add end-to-end PostgreSQL/Temporal/Redpanda/Action Gateway failure-recovery coverage in `tests/integration/test_containment_recovery.py`, including worker restart, duplicate events, stale policy, unknown remote result, and verification ambiguity.
- [ ] T102 [US3] Add redacted operator/audit trace fixtures in `tests/fixtures/audit/containment_trace.json` and verify that every attempted action ends as verified success, verified failure, or escalation in `tests/integration/test_action_terminal_outcomes.py`.
- [ ] T103 [US3] Run the US3 vertical-slice gate and safety evidence export in `tests/integration/test_us3_containment_slice.py` and `docs/validation/us3-containment.md`; include measured outcomes only and preserve replay/live labels.

**Checkpoint**: US3 is independently safe: no approval bypass, no direct model side effect, unknown results reconcile before retry, verification is mandatory, and case closure uses only the three explicit terminal outcomes.

---

## Phase 6: User Story 4 — Demonstrate and replay the complete flow (Priority: P2)

**Goal**: Demonstrate the same versioned flow live when configured or through labeled deterministic replay, with honest evaluation, complete observability, Compose topology, CI, and reviewer UI.

**Independent Test**: Execute or replay the canonical fixture, compare recorded deterministic outputs and audit links, inspect the operator workflow, and verify that unavailable providers produce labeled replay/escalation rather than fabricated live results.

### Replay, evaluation, and performance tests

- [ ] T104 [P] [US4] Add replay-run and evaluation-record contract tests in `tests/contract/test_replay_evaluation.py` for fixture/provider/policy/model/environment provenance, split metadata, labels, outcomes, and confidence-interval metadata.
- [ ] T105 [P] [US4] Add canonical replay determinism tests in `tests/integration/test_canonical_replay.py` for identical timeline, exposure, policy, proposal-validation, terminal-state, and audit outputs under the same inputs/versions/seed.
- [ ] T106 [P] [US4] Add deterministic replay-variant tests in `tests/integration/test_replay_variants.py` for invalid signatures, duplicates, out-of-order events, missing evidence, policy denial, approval gating, unknown remote results, forbidden proposals, verification failure, escalation, and provider unavailability.
- [ ] T107 [P] [US4] Add grouped split and leakage tests in `tests/evaluation/test_dataset_splits.py` for entity/customer and temporal separation before synthetic overlays, 60/20/20 development/validation/sealed-held-out metadata, and inaccessible held-out seeds/scenarios.
- [ ] T108 [P] [US4] Add evaluation metric and confidence-interval tests in `tests/evaluation/test_metrics.py` for malicious-action precision/recall, contained value, legitimate value disrupted, resolution success, latency, tool efficiency, forbidden attempts/executions, model cost, provenance, and actual sample size.
- [ ] T109 [P] [US4] Add complete Compose health/smoke tests in `tests/integration/test_compose_topology.py` for all services, internal-only data/gateway administration, live-action-disabled defaults, and provider-unavailable replay.
- [ ] T110 [US4] Add browser acceptance tests in `tests/browser/test_operator_workflow.py` for incident scope, legitimate/malicious activity, remaining exposure, containment outcome, next human decision, audit traceability, approval, escalation, and replay labels without editing underlying records.

### Replay and benchmark/evaluation harness

- [ ] T111 [US4] Implement the labeled live/replay runner in `backend/replay/runner.py` and `backend/api/replay.py` using the same connector/action contracts and versioned policy/model inputs.
- [ ] T112 [US4] Create the canonical end-to-end mixed legitimate/attacker fixture in `tests/fixtures/canonical/incident.json`, including expected stage outcomes, evidence references, policy decisions, action outcomes, audit links, and terminal result.
- [ ] T113 [US4] Create deterministic replay variants in `tests/fixtures/canonical/variants/` and `backend/replay/variants.py` for every required invalid, duplicate, ordering, evidence, policy, approval, forbidden, unknown-result, verification, escalation, and provider-unavailability scenario.
- [ ] T114 [US4] Define benchmark provenance, labels, class-balance fields, and corpus manifest in `evaluation/manifest.schema.json`, `evaluation/manifest.yaml`, and `evaluation/README.md`; target at least 500 cases when feasible and never fabricate or pad cases.
- [ ] T115 [US4] Implement leakage-safe grouped entity/customer and temporal split validation before synthetic overlay generation in `evaluation/splitting.py` and `evaluation/tests/test_split_order.py`.
- [ ] T116 [US4] Implement sealed held-out seed/scenario access controls in `evaluation/sealed_store.py`, `evaluation/held_out_policy.py`, and `evaluation/tests/test_holdout_sealing.py`; prompts, tuning, and model selection cannot read held-out inputs.
- [ ] T117 [US4] Implement the benchmark/evaluation harness in `evaluation/runner.py`, `evaluation/metrics.py`, `evaluation/confidence_intervals.py`, and `evaluation/report.py`; target at least 150 labeled incidents with 60/20/20 split metadata, target at least 100 held-out cases and preferably 150 or more, enforce at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases, and report shortfalls/statistical limitations honestly.
- [ ] T118 [US4] Implement measured-baseline capture and classification in `evaluation/performance.py` and `docs/validation/performance-baseline.md` for actual p50/p95 latency, throughput, recovery time, and failure rates; compare provisional p95 intake <=2 seconds and replay <=5 minutes targets without calling them release SLOs.
- [ ] T119 [US4] Integrate redacted model traces, evaluation metadata, dashboards, logs, and trace correlation in `backend/observability/evaluation.py`, `infra/observability/grafana/dashboards/fs001.json`, `infra/langfuse/config.yaml`, and `infra/mlflow/config.yaml`.

### Docker Compose, CI, and operator UI

- [ ] T120 [US4] Define the authoritative Docker Compose topology in `infra/docker-compose.yml`, `infra/docker-compose.test.yml`, and `infra/networks.yml` for web, API, workflow worker, model gateway, attribution, evidence connectors, Action Gateway, PostgreSQL, Temporal, Redpanda, Neo4j, MinIO, Redis, Keycloak, Vault, OpenTelemetry, Prometheus, Grafana, Loki, Langfuse, and MLflow; expose only UI/API ingress and keep live financial actions disabled.
- [ ] T121 [US4] Implement GitHub Actions validation in `.github/workflows/ci.yml`, `.github/workflows/security.yml`, and `.github/workflows/evaluation.yml` for lint, type checks, unit/property/contract/integration/security/acceptance tests, Compose smoke, migration checks, sealed-evaluation controls, and artifact provenance.
- [ ] T122 [US4] Implement the Next.js operator case-review workflow in `frontend/src/app/cases/[caseId]/page.tsx`, `frontend/src/components/case/CaseTimeline.tsx`, `frontend/src/components/case/ExposureSummary.tsx`, and `frontend/src/components/case/ActionDecisionPanel.tsx`; show tenant, provenance, uncertainty, policy result, approval state, remaining exposure, terminal outcome, and next human decision.
- [ ] T123 [US4] Implement typed intake, approval, escalation, replay, audit, and evaluation UI commands/read models in `frontend/src/lib/api.ts`, `frontend/src/components/case/ApprovalPanel.tsx`, `frontend/src/components/case/EscalationPanel.tsx`, `frontend/src/components/replay/ReplayPanel.tsx`, and `frontend/src/components/audit/AuditTrace.tsx`; UI cannot write underlying records or bypass APIs.
- [ ] T124 [US4] Implement live/replay availability detection and honest labeling in `backend/replay/mode_selection.py`, `backend/api/demo.py`, and `frontend/src/components/replay/ModeBadge.tsx`; provider/connector unavailability must select replay or escalation and never fabricate live results.
- [ ] T125 [US4] Execute the quickstart validation flow in `tests/acceptance/test_quickstart_flow.py` and record only actual evidence in `docs/validation/fs001-quickstart.md`, covering Compose health, canonical flow, variants, projection rebuild, evaluation metadata, dashboards, and reviewer traceability.

**Checkpoint**: US4 demonstrates the complete feature in live/replay mode with reproducible artifacts, honest metrics, complete operator views, and the full approved topology.

---

## Phase 7: Polish and cross-cutting hardening

**Purpose**: Close the feature with explicit fault/chaos, security, observability, performance, documentation, and release-readiness checks. These tasks do not replace slice-specific tests.

- [ ] T126 [P] Add fault/chaos scenarios and recovery assertions in `tests/chaos/test_fault_matrix.py` for PostgreSQL, Temporal worker, Redpanda, Neo4j, MinIO, Redis, Keycloak, Vault, model provider, evidence connector, Action Gateway timeout, and verification ambiguity.
- [ ] T127 [P] Run the cross-tenant, least-privilege, untrusted-evidence, PII, approval self-dealing, audit-tampering, arbitrary-network, and forbidden-action hardening suite in `tests/security/test_fs001_hardening.py`.
- [ ] T128 [P] Verify service credential and network egress policies in `infra/security/network-policies.yml`, `infra/security/service-accounts.yml`, `infra/security/credential-audit.yml`, and `tests/security/test_credential_network_boundaries.py`; agent/model identities must have no action credentials.
- [ ] T129 [P] Run the documented simulator intake/replay performance baseline in `tests/performance/test_fs001_baseline.py` and update `docs/validation/performance-baseline.md` with environment, p50/p95, throughput, recovery time, failure rates, and limitations.
- [ ] T130 Run the full mixed legitimate/attacker end-to-end acceptance suite in `tests/acceptance/test_fs001_complete_flow.py`; require 100% explicit stage outcomes, zero forbidden executions, no duplicate non-idempotent effects, valid approvals, verified/escalated terminal state, and traceable audit.
- [ ] T131 Update implementation traceability and operator documentation in `docs/architecture/fs001-traceability.md`, `docs/operator/reviewer-workflow.md`, and `docs/operator/replay-and-escalation.md` with links to actual tests and measured artifacts only.
- [ ] T132 Reconcile the milestone status from actual artifacts and checks in `PROJECT_STATUS.md`; record tasks complete, implementation status, test/evaluation status, and any environment shortfalls without inventing metrics or completion percentages.
- [ ] T133 Run final diff/checklist validation in `scripts/validate_fs001_artifacts.ps1`, including contract version consistency, migration coverage, task-to-FR traceability, no generic `closed` state, live-action-disabled defaults, no unsealed holdout access, and clean formatting.

---

## Requirement and planning-artifact traceability

The task IDs below explicitly cover every functional requirement in `spec.md`; the planning artifacts named in each row are the source of the implementation constraint.

| Requirement | Covered by tasks | Planning artifacts |
|---|---|---|
| FR-001 | T036, T044, T047 | `spec.md`; `contracts/intake-webhook.md`; `data-model.md` Incident |
| FR-002 | T037, T045, T046, T048 | `spec.md`; `contracts/intake-webhook.md`; research Razorpay decision |
| FR-003 | T019, T020, T044, T047, T053 | `spec.md`; `data-model.md`; ADR-001 |
| FR-004 | T011, T016, T039, T050, T051 | `spec.md`; `contracts/connectors.md`; plan Slice 2 |
| FR-005 | T021, T028, T040, T053, T054, T070 | `spec.md`; `data-model.md` EvidenceItem; ADR-002 |
| FR-006 | T038, T041, T055 | `spec.md`; `data-model.md` TimelineEvent; plan Slice 2 |
| FR-007 | T019, T023, T026, T038, T045, T048, T055, T095 | `spec.md`; `contracts/events.md`; `data-model.md` invariants |
| FR-008 | T059, T060, T066, T067, T069 | `spec.md`; `data-model.md` Attribution; plan Slice 3 |
| FR-009 | T063, T070–T078 | `spec.md`; `contracts/analysis-policy.md`; ADR-002 |
| FR-010 | T059, T062, T066, T069, T074, T097 | `spec.md`; `data-model.md` Attribution; plan Slice 3/4 |
| FR-011 | T061, T068, T083, T094 | `spec.md`; `data-model.md` FinancialExposure; constitution III |
| FR-012 | T011, T014, T064, T073–T075, T093 | `spec.md`; `contracts/connectors.md`; ADR-002 |
| FR-013 | T079, T080, T088, T089, T091 | `spec.md`; `contracts/analysis-policy.md`; research policy decision |
| FR-014 | T079, T088, T092, T093, T100 | `spec.md`; plan Slice 5; ADR-002 |
| FR-015 | T081, T083, T089, T090, T099 | `spec.md`; `data-model.md` Approval; research separation-of-duties decision |
| FR-016 | T014, T019, T023, T082, T092, T095 | `spec.md`; `contracts/action-gateway.md`; ADR-002 |
| FR-017 | T082, T084, T095, T096, T101 | `spec.md`; `data-model.md` ActionExecution; plan Slice 5 |
| FR-018 | T085, T086, T096, T098, T102 | `spec.md`; `contracts/action-gateway.md`; research terminal-outcome decision |
| FR-019 | T085–T087, T097, T098, T102, T130 | `spec.md`; `data-model.md` Escalation; plan Slice 5 |
| FR-020 | T015, T021, T048, T076, T091, T098, T102, T123 | `spec.md`; `contracts/audit-replay.md`; ADR-001/002 |
| FR-021 | T104–T106, T111–T113, T124 | `spec.md`; `contracts/audit-replay.md`; ADR-003 |
| FR-022 | T019, T030, T031, T034, T063, T070, T127, T128 | `spec.md`; constitution VII; plan security check |
| FR-023 | T034, T063, T064, T073, T076, T127, T128, T130 | `spec.md`; ADR-002; constitution I/II |
| FR-024 | T021, T053, T069, T076, T091, T099, T102, T122–T123 | `spec.md`; `data-model.md`; quickstart.md |
| FR-025 | T104, T107, T108, T114–T118 | `spec.md`; `contracts/audit-replay.md`; ADR-003 |

## Safety-critical acceptance criteria

- PostgreSQL remains authoritative for business, policy, approval, action, verification, escalation, audit, replay, and evaluation state; Temporal recovery never substitutes workflow history for business truth (T018–T025, T100, T130).
- No forbidden action is executed; every forbidden attempt is rejected/quarantined and audited; the model has no side-effect credentials or unrestricted tools (T034, T063–T064, T073, T076, T127–T128, T130).
- Refunds require captured payment, positive unreimbursed amount, explicit currency, and the original payment source; live financial execution remains disabled by default (T061, T068, T083–T084, T094).
- Approval-required cancellation, refund, and identity restoration cannot execute without a valid non-self approval under the applicable immutable policy version (T080–T091, T099–T101).
- Unknown remote results reconcile before retry, duplicate idempotency keys do not issue duplicate non-idempotent requests, and inconclusive verification escalates (T082–T087, T095–T102, T126).
- Terminal outcomes are only `verified_contained`, `verified_failed`, or `escalated_unresolved`; generic `closed` is forbidden (T086, T098, T102, T130, T133).
- Replay is labeled, uses the same versioned contracts, and cannot be represented as live production fraud performance; evaluation reports provenance, actual counts, confidence intervals, and shortfalls (T104–T119, T124–T125).

## Dependencies and execution order

### Phase dependencies

1. **Phase 1 Setup** has no feature dependencies.
2. **Phase 2 Foundation** depends on Phase 1 and blocks all user-story work.
3. **Phase 3 US1** depends on Phase 2 and produces the authoritative case/evidence/timeline consumed by later slices.
4. **Phase 4 US2** depends on Phase 3's timeline/evidence outputs and produces trusted exposure plus typed proposals.
5. **Phase 5 US3** depends on Phase 4's validated proposals and Phase 2's policy/audit foundations; it produces verified/escalated terminal outcomes.
6. **Phase 6 US4** depends on the complete US1–US3 flow and produces replay/evaluation/demo/UI evidence.
7. **Phase 7 Polish** depends on the slices selected for delivery and must pass before FS-001 implementation is declared release-ready.

### Within-slice ordering

- Contract tests precede the corresponding contract implementation or adapter completion.
- Storage/schema and repository work precede services; services precede APIs/workflow activities; workflow activities precede full acceptance tests.
- US1 intake and evidence persistence precede timeline reconstruction; timeline reconstruction precedes US2 attribution/exposure.
- US2 deterministic validation precedes policy evaluation; policy and approval decisions precede Action Gateway submission; gateway execution precedes reconciliation and verification; verification precedes terminal state.
- Replay fixture/variant definitions precede evaluation runs and UI demonstration claims.

### Parallelizable groups

- **Setup**: T002–T005 and T007–T008 can proceed in parallel after T001, provided they do not edit the same lock/config files concurrently.
- **Foundation contracts**: T010–T015 can proceed in parallel after T009; T017 follows all contract definitions and precedes the dependent registry service implementation T016. T016 then validates registry behavior with its colocated registry contract tests.
- **Foundation platform**: T018–T023, T027–T032, and T034 can proceed in parallel after T009 where their files are isolated; T024–T026 depend on the event/workflow contracts.
- **US1 tests**: T036–T042 can proceed in parallel; implementation T045–T046, T050–T051, and T054 can proceed in parallel after their contract foundations; T055–T058 follow persisted evidence.
- **US2 tests**: T059–T064 can proceed in parallel; T066–T069 are parallel after US1; T070–T076 are parallel by boundary after the analysis contracts, with T075 before T078.
- **US3 tests**: T079–T086 can proceed in parallel; T088–T091 (policy/control plane) can proceed separately from T092–T094 (gateway adapters) after US2 proposals; T095–T102 then follow the gateway state contract.
- **US4 tests**: T104–T110 can proceed in parallel; T111–T119 are separable by replay, evaluation, and observability concerns; T120–T124 are separable by deployment, CI, frontend, and mode selection after API contracts exist.
- **Hardening**: T126–T129 can proceed in parallel; T130–T133 require the resulting implementation and artifacts.

## MVP and incremental delivery strategy

### MVP

The minimum useful vertical slice is Phases 1–3: complete the foundation, then demonstrate US1 intake through deterministic, tenant-isolated evidence/timeline. It is not a containment release and must not be described as such until US2 and US3 safety gates pass.

### Containment increment

Add Phase 4 and Phase 5 to produce trusted exposure, typed proposals, immutable policy/approval decisions, isolated execution, reconciliation, verification, and explicit terminal outcomes. This is the first increment eligible for the complete FS-001 containment acceptance flow.

### Demonstration/evaluation increment

Add Phase 6 for canonical replay, deterministic variants, honest evaluation, observability, Compose, CI, and operator workflow. Complete Phase 7 before claiming implementation readiness; measured performance and benchmark results remain environment- and dataset-qualified.

## Implementation handoff

Implementation must start with T001 and proceed through the dependency structure above. No task in this file authorizes production financial execution, attacker interaction, arbitrary network access, credential probing, direct model side effects, or replacing the approved architecture.
