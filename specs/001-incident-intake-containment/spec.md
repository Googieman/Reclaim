# Feature Specification: Incident Intake to Verified Containment

**Feature Branch**: `main` (no feature branch created)

**Created**: 2026-08-30

**Status**: Approved

**Input**: User description: "FS-001 — Incident Intake to Verified Containment. Implement the first complete RECLAIM vertical slice from an account-compromise report through verified merchant loss containment, preserving the approved production-oriented architecture."

## Scope and Boundaries

This feature delivers one complete, tenant-ready demonstration flow for a merchant-controlled account-compromise incident. It begins with an incident report and ends with verified containment, a verified failure, or an explicit escalation.

In scope are incident intake, applicable Razorpay Test Mode webhook intake, evidence collection from approved merchant-controlled connectors, deterministic timeline reconstruction, event attribution, exposure calculation, bounded analysis, typed defensive proposals, policy and approval gates, idempotent execution, reconciliation, verification, escalation, append-only audit, and live/replay demonstration support.

Out of scope are production financial execution, actions against systems not controlled by the merchant or explicitly configured connectors, attacker interaction or surveillance, credential probing, arbitrary network access, and any agent-directed side effect. The approved RECLAIM architecture remains governing context; this specification does not authorize replacing or omitting its components for convenience.

## Clarifications

### Session 2026-08-30

- Q: Should Razorpay Test Mode webhooks require verified authenticity and provider event identity before case processing, with duplicate deliveries treated as no-ops? (FR-002, FR-007, FR-016) → A: Require the configured provider authenticity check over the original payload, require a provider event identifier, persist the raw payload and checksum, quarantine invalid or incomplete events, and make `(tenant, connector, provider_event_id)` idempotent; duplicate valid deliveries acknowledge without reprocessing.
- Q: Should every evidence and action connector use a versioned, tenant-scoped contract with explicit allowlisted resources and operations, while simulators implement that same contract and expose controlled failure cases? → A: Require each connector to declare its tenant scope, resources, operations, authentication scope, input/output schema, and failure states; require simulators to implement the identical contract and support deterministic partial, stale, duplicate, out-of-order, timeout, and unknown-result fixtures.

- Q: Who should own policy thresholds, and how should those thresholds be changed? (FR-013, FR-014, FR-015) -> A: Authorized policy owners define versioned thresholds; tenant configuration is allowed only within centrally enforced bounds; policy changes require approved change control; models cannot change policy at runtime.
- Q: Should high-impact approvals require separation of duties, with unresolved cases assigned to an owner and closed only through explicit terminal states? (FR-015, FR-018, FR-019) -> A: Keep analysis/proposal, approval, and escalation responsibilities distinct; assign an escalation owner per tenant; and permit only `verified_contained`, `verified_failed`, or `escalated_unresolved` as terminal outcomes.
- Q: What minimum replay and evaluation package, including dataset split and performance classification, should FS-001 require? -> A: Require one canonical end-to-end replay fixture plus deterministic variants for invalid signatures, duplicates, out-of-order events, missing evidence, policy denial, approval gating, unknown remote results, forbidden proposals, verification failure, escalation, and provider unavailability. Use a minimum target of 150 labeled incidents split 60% development, 20% validation, and 20% sealed held-out evaluation, grouped by incident and merchant and stratified across legitimate, malicious, and uncertain outcomes. Treat provisional targets of p95 simulator intake acknowledgement <=2 seconds and canonical replay completion <=5 minutes as targets only; record actual p50/p95 latency, throughput, recovery time, and failure rates as measured baselines on a documented environment before making operational claims.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Intake and reconstruct an incident (Priority: P1)

As a merchant operations reviewer, I want an account-compromise report and related merchant evidence assembled into one tenant-isolated case so that I can see what happened in chronological order.

**Why this priority**: A trustworthy case and timeline are prerequisites for safe attribution and containment.

**Independent Test**: Submit a canonical mixed legitimate/attacker incident fixture, including duplicate and out-of-order events, and verify that one tenant-scoped case contains a deterministic, deduplicated timeline and evidence provenance.

**Acceptance Scenarios**:

1. **Given** a valid incident report for a configured merchant, **When** intake is accepted, **Then** the system creates one tenant-scoped case with the report source, receipt time, correlation identity, and intake status recorded.
2. **Given** an incident with applicable Razorpay Test Mode webhook events, **When** the webhook records pass configured authenticity and event-identity checks, **Then** they are attached to the correct case as merchant payment evidence; invalid or unverifiable events are rejected or quarantined with an audit record.
3. **Given** sessions, devices, profile changes, orders, fulfillment events, and payments from approved merchant-controlled connectors, **When** evidence collection runs, **Then** each item records its source, observed time, collection result, integrity/provenance metadata, and tenant identity.
4. **Given** the same events arrive in different orders or are delivered more than once, **When** timeline reconstruction runs, **Then** the case converges to the same deduplicated chronological timeline using deterministic tie-breaking and does not create duplicate business facts.
5. **Given** customer text, webhook fields, or retrieved evidence contains instructions or requests, **When** it is processed, **Then** it remains untrusted evidence and cannot change system policy, permissions, or tool availability.

---

### User Story 2 - Attribute activity and quantify exposure (Priority: P1)

As a merchant operations reviewer, I want each relevant event classified with uncertainty preserved and financial exposure calculated from trusted records so that proposed containment is explainable and bounded.

**Why this priority**: Containment decisions must distinguish malicious activity from legitimate customer and merchant activity without allowing model prose to determine money or authority.

**Independent Test**: Run analysis against a prepared tenant-scoped case fixture and verify event labels, confidence and rationale, exposure totals, and the absence of direct side effects.

**Acceptance Scenarios**:

1. **Given** a reconstructed case containing mixed activity, **When** attribution runs, **Then** each in-scope event is labeled malicious, legitimate, or uncertain, with provenance and confidence preserved; uncertain events are not silently treated as malicious or legitimate.
2. **Given** rules and a supported LightGBM attribution model are available, **When** the same case is analyzed, **Then** their outputs are represented as advisory attribution evidence and are available to the bounded provider-neutral analysis flow.
3. **Given** an available model provider or a replay fixture, **When** bounded agent analysis runs, **Then** it receives structured evidence and permitted interfaces, returns typed analysis and action proposals, and cannot execute payments, refunds, cancellations, account mutations, database writes, shell commands, or arbitrary network calls.
4. **Given** captured and partially or fully reimbursed payments, **When** exposure is calculated, **Then** the result uses integer minor currency units and explicit currency, references only existing captured payments, and reports exposure, recoverable value, contained value, legitimate value disrupted, irreversible loss, and remaining exposure deterministically.
5. **Given** no captured payment or insufficient evidence for a refund, **When** exposure and proposal generation run, **Then** no refund proposal is created for that amount and the missing evidence or unresolved condition is recorded.
6. **Given** an analysis output requests a forbidden action or exceeds the case tenant or connector scope, **When** proposals are validated, **Then** the request is rejected, no side effect occurs, and the forbidden attempt is auditable.

---

### User Story 3 - Contain loss safely and verify the result (Priority: P1)

As a merchant operations reviewer, I want only policy-permitted actions to execute and every uncertain or unresolved outcome to be reconciled or escalated so that containment does not create additional loss.

**Why this priority**: Verified, bounded containment is the business outcome of the vertical slice; action execution without these safeguards is unacceptable.

**Independent Test**: Start from a prepared case with policy-approved reversible actions, approval-gated actions, an idempotent retry, and an unknown remote result, then verify gateway behavior, reconciliation, verification, and escalation outcomes.

**Acceptance Scenarios**:

1. **Given** a typed suspicious-session revocation or eligible fulfillment-hold proposal that passes the current policy, **When** required automatic-action conditions are satisfied, **Then** the isolated Action Gateway executes it with a stable idempotency key and records the request, result, and tenant scope.
2. **Given** a cancellation, refund, or identity-affecting restoration proposal, **When** the required approval is absent, **Then** the action is not executed and the case remains pending approval or is escalated according to policy.
3. **Given** a refund proposal, **When** policy evaluation runs, **Then** it is limited to an existing captured payment, the unreimbursed amount, and the original payment source; deterministic financial validation occurs before gateway execution.
4. **Given** a gateway call has an unknown remote result, **When** recovery is requested, **Then** the system reconciles the remote state before any retry and never repeats a non-idempotent side effect based only on timeout or process failure.
5. **Given** an action reports completion, **When** verification runs, **Then** the system checks the merchant-controlled resulting state and closes the action only as verified success or verified failure; otherwise it records ambiguity and escalates.
6. **Given** evidence remains uncertain or loss is irreversible or unresolved, **When** policy and verification complete, **Then** the system creates an explicit escalation with the remaining exposure, reason, evidence references, recommended human decision, and current case state.

---

### User Story 4 - Demonstrate and replay the complete flow (Priority: P2)

As a reviewer, I want to run the same incident live when dependencies are available or replay it deterministically when they are not so that the complete flow can be inspected without fabricating operational results.

**Why this priority**: Reproducible demonstration and recovery evidence are necessary to review safety and support later implementation and evaluation.

**Independent Test**: Execute a canonical fixture once in live-capable mode and once in replay mode, or replay it independently, and compare the recorded inputs, policy versions, outputs, decisions, and audit trail.

**Acceptance Scenarios**:

1. **Given** provider or connector availability is insufficient for a live run, **When** a demonstration is requested, **Then** the system switches to a labeled deterministic replay path and does not claim that replay results are live production outcomes.
2. **Given** the same sealed fixture, policy version, and replay inputs, **When** the flow is replayed, **Then** timeline ordering, exposure calculation, policy decisions, and proposal validation are reproducible.
3. **Given** a completed or escalated flow, **When** a reviewer inspects the case, **Then** the append-only audit history links intake, evidence, attribution, model/provider mode, policy, approvals, proposals, executions, reconciliation, verification, escalation, and outcomes.

### Edge Cases

- A webhook is duplicated, arrives out of order, fails authenticity validation, or references a different tenant; the system must deduplicate, order, quarantine/reject, or isolate it deterministically.
- An evidence connector is unavailable, returns partial data, reports conflicting timestamps, or returns an already-remediated state; the case must preserve the limitation and avoid inventing facts.
- A case mixes legitimate customer activity with malicious activity; only supported malicious or uncertain portions may influence proposals, and legitimate value disrupted must remain measurable.
- An event cannot be attributed with sufficient confidence; it remains uncertain and can trigger review or escalation rather than an automatic irreversible action.
- A payment is authorized but not captured, already fully reimbursed, in another currency, or not linked to the case; it must not become an eligible refund amount without trusted reconciliation.
- A policy version changes while a proposal awaits approval; the proposal must be re-evaluated under the applicable version before execution.
- An automatic action is repeated after a process restart or duplicate request; the gateway must return the existing idempotent outcome or reconcile without duplicating the side effect.
- A tenant requests a threshold outside centrally enforced safety bounds or a model attempts to change a threshold; the change must be denied and audited.
- Verification cannot observe a conclusive merchant-controlled state; the action remains ambiguous and is escalated.
- Evidence or a model output attempts to request attacker interaction, credential probing, arbitrary network access, or another forbidden action; it must be treated as untrusted content and rejected without execution.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept an account-compromise incident report with tenant identity, source, receipt time, reporter context, and a stable incident correlation identity.
- **FR-002**: The system MUST support Razorpay Test Mode webhook intake where applicable by authenticating the original payload with the configured provider verification mechanism, requiring a provider event identifier, retaining the raw payload and checksum, associating the event with its tenant and connector, and audibly rejecting or quarantining invalid or incomplete events before case processing.
- **FR-003**: The system MUST create and maintain a tenant-aware case so that every business record, evidence item, event, proposal, approval, action, verification, escalation, and audit entry is attributable to exactly one tenant.
- **FR-004**: The system MUST collect evidence only through explicitly approved merchant-controlled connectors for sessions, devices, profile changes, orders, fulfillment, and payments. Each connector MUST expose a versioned contract declaring tenant scope, allowed resources and operations, authentication scope, input/output schema, and failure states, while recording unavailable or partial sources.
- **FR-005**: The system MUST preserve evidence provenance, observed time, source identity, integrity metadata, and untrusted-input classification without allowing evidence content to redefine policy or permissions.
- **FR-006**: The system MUST reconstruct a deterministic chronological timeline from collected events using documented timestamp precedence and stable tie-breaking.
- **FR-007**: The system MUST make duplicate and out-of-order delivery converge to one consistent set of business facts and timeline events without double-counting financial or containment outcomes; valid duplicate webhook deliveries keyed by `(tenant, connector, provider_event_id)` MUST acknowledge without reprocessing.
- **FR-008**: The system MUST support rules-based and LightGBM-based attribution evidence, retaining the inputs, version, label, confidence, and rationale for each result.
- **FR-009**: The system MUST provide bounded provider-neutral agent analysis through the approved LangGraph/LiteLLM model boundary, using structured case representations and typed interfaces, with no direct side-effect authority.
- **FR-010**: The system MUST represent malicious, legitimate, and uncertain event attribution distinctly and MUST preserve uncertainty through policy evaluation and escalation.
- **FR-011**: The system MUST calculate financial exposure deterministically in integer minor currency units with explicit currency and trusted payment state, including contained value, legitimate value disrupted, irreversible loss, recoverable value, and remaining exposure.
- **FR-012**: The system MUST emit only typed defensive action proposals from analysis and MUST restrict proposals to explicitly allowlisted merchant-controlled operations exposed through versioned connector contracts; simulators MUST enforce the same allowlists as live connectors.
- **FR-013**: The system MUST evaluate every proposal against a versioned deterministic policy covering tenant, permissions, confidence, resource state, amount, reversibility, customer impact, and approval requirements. Authorized policy owners MUST own policy thresholds; tenant-specific configuration MUST remain within centrally enforced safety bounds, policy versions MUST be immutable after publication, and a model MUST NOT modify policy at runtime.
- **FR-014**: The system MUST permit automatic execution only for policy-authorized reversible actions, including suspicious-session revocation and eligible fulfillment holds, using the threshold values from the evaluated policy version.
- **FR-015**: The system MUST require policy-defined approval before cancellation, refund, or identity-affecting restoration, MUST prevent execution while required approval is absent or invalid, and MUST enforce separation between the person or process proposing an action and the authorized approver.
- **FR-016**: The system MUST execute approved actions only through an isolated idempotent Action Gateway using stable idempotency keys and explicit execution state; webhook intake idempotency MUST remain distinct from action idempotency.
- **FR-017**: The system MUST reconcile an unknown remote result before retrying and MUST distinguish verified success, verified failure, and unresolved execution.
- **FR-018**: The system MUST verify the merchant-controlled state after each attempted action and MUST not treat an ambiguous result as success; action and case closure MUST use only explicit terminal outcomes.
- **FR-019**: The system MUST assign unresolved incidents to a tenant-scoped escalation owner and MUST escalate ambiguous execution, insufficient evidence, and irreversible loss with remaining exposure, reason, evidence links, and a human-reviewable recommendation. Terminal case outcomes MUST be limited to `verified_contained`, `verified_failed`, and `escalated_unresolved`; a generic successful `closed` state is not permitted.
- **FR-020**: The system MUST maintain append-only, evidence-linked audit records for intake, collection, reconstruction, attribution, model/provider mode, policy, approvals, proposals, execution, reconciliation, verification, escalation, and outcomes.
- **FR-021**: The system MUST support a labeled live/replay mode using the same versioned connector and action contracts. The canonical replay package MUST include deterministic variants for invalid signatures, duplicates, out-of-order events, missing evidence, policy denial, approval gating, unknown remote results, forbidden proposals, verification failure, escalation, and provider unavailability.
- **FR-022**: The system MUST provide tenant isolation and least-privilege access across case data, connectors, secrets, model calls, traces, proposals, and audit records, with PII minimized or redacted before model calls where practical.
- **FR-023**: The system MUST record forbidden action attempts and MUST execute zero forbidden actions, including attacker interaction, credential probing, arbitrary external-system access, unauthorized network activity, shell commands, or direct financial/account mutations by the agent.
- **FR-024**: The system MUST expose sufficient case state and audit evidence for a reviewer to understand why an event was attributed, why exposure was calculated, why an action was allowed or denied, and why a flow was verified or escalated.
- **FR-025**: The system MUST keep evaluation records labeled with dataset provenance, case counts, split membership, grouping identity, and class balance. The initial evaluation target MUST be at least 150 labeled incidents split 60% development, 20% validation, and 20% sealed held-out evaluation, with related records grouped by incident and merchant so they cannot cross splits.

### Key Entities

- **Incident**: The initial compromise report and its source, tenant, receipt metadata, and correlation identity.
- **Case**: The tenant-scoped investigation and containment state associated with one incident.
- **Evidence Item**: A merchant-controlled observation with source, provenance, integrity metadata, and collection status.
- **Timeline Event**: A deduplicated, chronologically ordered business-relevant event derived from evidence.
- **Attribution**: A malicious, legitimate, or uncertain assessment with confidence, rationale, and versioned provenance.
- **Financial Exposure**: A deterministic, currency-specific accounting of potentially recoverable and lost value.
- **Action Proposal**: A typed, bounded defensive action with target, rationale, policy context, and idempotency identity.
- **Policy Decision**: A versioned allow, deny, approval-required, or escalate result with evaluated conditions.
- **Approval**: A tenant-scoped authorization for an approval-required action, including approver identity, time, scope, policy version, and proof that the approver is distinct from the proposer.
- **Action Execution**: The isolated gateway request and its idempotent remote result or unknown state.
- **Verification**: Evidence that the intended merchant-controlled state was or was not achieved.
- **Escalation**: A tenant-scoped unresolved or irreversible outcome assigned to an escalation owner, with remaining exposure, evidence links, recommended decision, and terminal state `escalated_unresolved` when unresolved.
- **Audit Record**: An append-only, replayable record linking inputs, decisions, versions, side effects, and outcomes.
- **Replay Run**: A labeled execution over recorded inputs and versions used for demonstration, recovery, or evaluation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the canonical mixed legitimate/attacker acceptance fixture, 100% of incident, evidence, timeline, attribution, exposure, proposal, policy, execution, verification, and audit stages produce an explicit outcome of success, failure, or escalation.
- **SC-002**: Across duplicate and out-of-order delivery tests, 100% of repeated runs produce the same deduplicated timeline and financial totals as the canonical ordering.
- **SC-003**: Across the security acceptance suite, 0 forbidden actions are executed, and 100% of forbidden attempts are rejected or quarantined with audit evidence.
- **SC-004**: Across action-gateway recovery tests, 100% of unknown remote results are reconciled before retry, and no test produces a duplicate non-idempotent side effect.
- **SC-005**: Across approval-gate tests, 100% of cancellation, refund, and identity-affecting restoration attempts without valid approval are prevented from execution.
- **SC-006**: A reviewer can trace 100% of final exposure and containment decisions to tenant-scoped evidence, attribution, policy, approval, execution, verification, and audit records.
- **SC-007**: The canonical flow can be demonstrated in live mode when dependencies are configured and in labeled replay mode when they are unavailable, without presenting replay output as real production fraud performance.
- **SC-008**: In a reviewer usability walkthrough, a reviewer can identify the incident scope, affected legitimate and malicious activity, remaining exposure, containment outcome, and next human decision from the case and audit views without editing underlying records.
- **SC-009**: When the target evaluation dataset is available, the sealed held-out evaluation contains at least 30 labeled incidents and reports provenance, counts, grouping, class balance, and legitimate/malicious/uncertain outcomes; if the target volume is unavailable, the shortfall is reported and no production-performance claim is made.
- **SC-010**: On a documented test environment using deterministic simulators, p95 intake acknowledgement of 2 seconds or less and canonical replay completion of 5 minutes or less are treated as provisional targets; actual p50/p95 latency, throughput, recovery time, and failure rates are recorded separately as measured baselines.

## Assumptions

- The initial demonstration uses one demo merchant but all business state and access paths are tenant-ready.
- Razorpay access is Test Mode only for this feature; live financial execution remains disabled by default and requires separately configured credentials, policy, approvals, and verification.
- The approved production-oriented RECLAIM architecture—including PostgreSQL authority, Temporal durability, Redpanda events, Neo4j projection, Redis limitations, merchant evidence storage, LangGraph/LiteLLM bounded analysis, rules/LightGBM support, and the isolated Action Gateway—remains mandatory and will be mapped during planning.
- Connectors are explicitly configured and merchant-controlled; unsupported, unavailable, or partial evidence is reported rather than inferred.
- Live connectors and deterministic simulators share versioned contracts and enforce the same tenant, resource, operation, authentication, schema, and failure-state boundaries.
- Timestamps are normalized to UTC for ordering, with original source timestamps retained for audit.
- Monetary values are represented in integer minor units with explicit currency; cross-currency conversion is not inferred without a trusted rate and recorded source.
- A valid approval in the demonstration is produced by an authenticated reviewer action or a clearly labeled test fixture from a role distinct from the proposer; no approval requirement is bypassed for convenience.
- Authorized policy owners control threshold changes through versioned, approved change control; models and ordinary case reviewers cannot change policy at runtime.
- Provider unavailability, network restrictions, or missing integration credentials cause a labeled replay or escalation path rather than fabricated live results.
- The canonical replay package includes one complete flow and deterministic variants for invalid signatures, duplicates, out-of-order events, missing evidence, policy denial, approval gating, unknown remote results, forbidden proposals, verification failure, escalation, and provider unavailability.
- The initial evaluation target is at least 150 labeled incidents with a grouped, stratified 60% development, 20% validation, and 20% sealed held-out split; fewer cases must be reported as a limitation rather than padded or represented as production evidence.
- The provisional performance targets are p95 simulator intake acknowledgement within 2 seconds and canonical replay completion within 5 minutes; measured baselines must be collected separately on a documented environment before operational claims are made.
