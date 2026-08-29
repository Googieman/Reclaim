# FS-001 Data Model

## Authority and identity rules

- Every entity below carries `tenant_id` directly or through a tenant-scoped parent; repositories and database policies must enforce the boundary.
- Business identifiers are opaque, stable, and independent of provider identifiers.
- Provider event identity is unique within `(tenant_id, connector_id, provider_event_id)`; action identity is separate and uses a stable proposal/action idempotency key.
- Monetary values are integer minor units with explicit ISO currency; no floating-point financial state is persisted.
- Raw evidence/artifacts are immutable objects addressed by checksum; normalized facts retain source and evidence references.
- Audit records are append-only and reference the policy, model/provider, approval, execution, and verification versions used.

## Authoritative entities

### Tenant

Represents a merchant boundary.

Key fields: `tenant_id`, display name, status, connector configurations, policy configuration bounds, roles, created/updated timestamps.

Rules: inactive tenants cannot intake or act; credentials and connector scopes are tenant-bound.

### Incident

Represents the initial compromise report or accepted webhook correlation.

Key fields: `incident_id`, `tenant_id`, source, reporter context, received time, correlation key, raw input reference, intake status, deduplication identity.

### Case

Represents the investigation and containment lifecycle.

Key fields: `case_id`, `tenant_id`, `incident_id`, current state, escalation owner, workflow identity, created/updated times, terminal time.

State: `intake_received -> collecting_evidence -> timeline_ready -> analyzed -> action_pending -> containing -> verified_contained | verified_failed | escalated_unresolved`.

Rules: terminal states are immutable except for append-only follow-up records; no generic successful `closed` state exists; unresolved or irreversible conditions enter `escalated_unresolved`.

### ConnectorConfiguration

Declares a merchant-controlled connector or deterministic simulator.

Key fields: `connector_id`, `tenant_id`, contract version, connector type, allowed resources/operations, credential scope reference, enabled status, simulator/live mode, schema and failure-state versions.

Rules: no connector call is valid without tenant and allowlist checks.

### EvidenceItem

Represents a raw or normalized merchant observation.

Key fields: `evidence_id`, `case_id`, `tenant_id`, connector, resource type, source identifier, observed/received times, raw object URI, checksum, normalization status, completeness, trust classification, collection error.

### TimelineEvent

Represents a deduplicated business fact.

Key fields: `timeline_event_id`, `case_id`, `tenant_id`, canonical event type, source event IDs, effective/observed time, ordering key, dedupe key, event payload, evidence references.

Rules: ordering is deterministic; duplicate source events merge rather than create new financial/action facts.

### Attribution

Represents advisory event assessment.

Key fields: `attribution_id`, timeline event, label (`malicious`, `legitimate`, `uncertain`), confidence, rationale, method, model/rules version, created time.

Rules: attribution never directly authorizes an action; uncertainty remains explicit.

### FinancialExposure

Represents trusted deterministic value accounting.

Key fields: `exposure_id`, case, currency, gross exposure, recoverable value, contained value, legitimate value disrupted, irreversible loss, remaining exposure, calculation version, source references.

Rules: captured payment and original source constraints are validated before refund eligibility; calculations are reproducible.

### PolicyVersion and PolicyDecision

PolicyVersion fields: `policy_version_id`, tenant or global scope, thresholds, allowlists, approval rules, effective interval, author, publication status, immutable checksum.

PolicyDecision fields: `decision_id`, proposal, policy version, evaluated conditions, result (`allow`, `deny`, `approval_required`, `escalate`), evaluator version, timestamp.

Rules: published versions are immutable; tenant values cannot exceed central safety bounds; models cannot write policy.

### ActionProposal

Represents a typed defensive proposal.

Key fields: `proposal_id`, case, tenant, action type, target resource, parameters, rationale/evidence references, attribution references, idempotency key, policy decision, status.

Rules: only allowlisted merchant-controlled operations; no free-form executable instruction.

### Approval

Represents authorization for a high-impact proposal.

Key fields: `approval_id`, proposal, tenant, approver identity/role, scope, policy version, created time, expiry/revocation, separation-of-duties evidence.

Rules: proposer and approver must be distinct; cancellation, refund, and identity-affecting restoration require valid approval.

### ActionExecution

Represents the Action Gateway attempt and remote state.

Key fields: `execution_id`, proposal, connector, idempotency key, request checksum, status (`not_started`, `pending`, `unknown`, `reconciled`, `verified_success`, `verified_failure`, `escalated`), remote reference, attempt count, timestamps, result reference.

Rules: unknown state blocks retry until reconciliation; execution does not imply verified success.

### Verification

Represents evidence of resulting merchant-controlled state.

Key fields: `verification_id`, execution, observed resource state, verifier source, result, evidence references, timestamp.

Rules: inconclusive verification is not success and routes to escalation.

### Escalation

Represents unresolved, ambiguous, or irreversible work.

Key fields: `escalation_id`, case, tenant, owner, reason, remaining exposure, evidence references, recommended human decision, state, created/resolved times.

Rules: unresolved terminal outcome is `escalated_unresolved`; ownership and audit are mandatory.

### AuditRecord

Represents append-only evidence-linked history.

Key fields: `audit_id`, tenant, case, actor/service, action, input/output references, policy/model/execution versions, correlation IDs, timestamp, previous-record linkage/checksum.

Rules: append-only, replayable, no secret or unnecessary PII storage.

### ReplayRun and EvaluationCase

ReplayRun fields: run identity, fixture/version, mode (`live`, `replay`), input/artifact references, policy/model versions, outcomes, environment metadata, label.

EvaluationCase fields: case identity, provenance, split (`development`, `validation`, `held_out`), entity/customer grouping identity, temporal boundary, synthetic-overlay lineage, class labels, no-compromise/false-alert flag, mixed-legitimate-malicious flag, expected outcomes, leakage checks, held-out seed/scenario access policy, and confidence-interval metadata.

Rules: target at least 500 benchmark cases when feasible; a 60/20/20 development/validation/sealed-held-out split is acceptable; target at least 100 held-out cases, preferably 150 or more. Held-out cases are sealed and grouped by entity/customer and time before synthetic overlays, with at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases. Held-out seeds/scenarios are inaccessible to prompts, tuning, and model selection. If fewer cases are available, record actual size and statistical limitations without padding. Replay results are labeled and never represented as live production results.

## Relationship summary

`Tenant 1->N Incident 1->1 Case 1->N EvidenceItem`

`Case 1->N TimelineEvent 1->N Attribution`

`Case 1->N FinancialExposure`

`Case 1->N ActionProposal 1->N PolicyDecision 0->1 Approval 1->N ActionExecution 1->N Verification`

`Case 0->N Escalation; all entities 1->N AuditRecord`

`Tenant 1->N ConnectorConfiguration; Case 1->N ReplayRun; ReplayRun 1->N EvaluationCase`

## State invariants

- A case cannot become terminal while an action has unknown execution or inconclusive verification unless it transitions to `escalated_unresolved`.
- A refund proposal cannot be allowed unless the payment is captured, unreimbursed amount is positive, currency is explicit, and the original payment source is known.
- A duplicate webhook cannot create a second incident fact, financial exposure, proposal, or remote side effect.
- A policy decision references exactly one immutable policy version; approval references the same applicable version and cannot be self-approved.
- A Neo4j or Redis outage does not change authoritative case, financial, action, or audit correctness.
