# FS-001 Planning Research

**Date**: 2026-08-30
**Scope**: Phase 0 research for Incident Intake to Verified Containment

This research records planning decisions derived from the approved RECLAIM constitution, the clarified FS-001 specification, and the repository's approved architecture. It does not claim that any external integration or benchmark has been executed.

## Decision: Preserve the full approved architecture

**Decision**: Implement the vertical slice across PostgreSQL, Temporal, Redpanda, Neo4j, Redis, MinIO, Keycloak/Vault, model/attribution services, observability services, and Docker Compose.

**Rationale**: The constitution makes ownership and safety boundaries architectural requirements. Omitting a component would hide integration and recovery behavior that the feature is intended to demonstrate.

**Alternatives considered**: A single-process MVP or in-memory event flow was rejected because it would bypass durable workflow, authoritative state, event transport, projection rebuild, credential isolation, and failure-recovery boundaries.

## Decision: PostgreSQL plus Temporal ownership split

**Decision**: PostgreSQL stores authoritative business state and audit; Temporal stores durable orchestration history and controls retries, timers, signals, and recovery.

**Rationale**: This avoids confusing workflow progress with business truth and allows a case to recover after worker/process failure without making Redis or an event offset authoritative.

**Alternatives considered**: A database-only job queue was rejected because it does not provide the required durable workflow semantics; Redis-only state was rejected by constitution.

## Decision: Transactional outbox/inbox for Redpanda

**Decision**: Business state changes and outbox records commit together in PostgreSQL; consumers use tenant-aware inbox/idempotency records before applying events.

**Rationale**: Redpanda is transport, not business truth. The pattern supports duplicate/out-of-order delivery and projection rebuild without losing authoritative history.

**Alternatives considered**: Direct database-to-event publishing was rejected because a process failure between writes can create missing or duplicated domain events.

## Decision: Strict Razorpay Test Mode webhook intake

**Decision**: Verify the original request payload using the configured provider authenticity mechanism, require a provider event identifier, persist raw payload/checksum, quarantine invalid or incomplete events, and key intake idempotency by `(tenant, connector, provider_event_id)`.

**Rationale**: Payment evidence must not influence exposure or actions until authenticity, tenant association, and event identity are established. Duplicate valid deliveries must acknowledge without reprocessing.

**Alternatives considered**: Hash fallback for missing provider IDs and simulator verification bypass were rejected because they weaken identity and trust boundaries. The exact provider header/secret handling is a connector implementation validation item and must be confirmed against configured Test Mode documentation before coding.

## Decision: Versioned connector/simulator contracts

**Decision**: Every evidence and action connector declares tenant scope, resources, operations, auth scope, schemas, and failure states. Deterministic simulators implement the same versioned contract and support partial, stale, duplicate, out-of-order, timeout, and unknown-result cases.

**Rationale**: Identical live and simulator interfaces prevent replay from becoming a separate untrusted code path and make failure recovery testable without external side effects.

**Alternatives considered**: Generic unrestricted reads and simulator-only APIs were rejected due to tenant and permission drift.

## Decision: Policy-owned immutable thresholds

**Decision**: Authorized policy owners publish immutable versioned policies. Tenant configuration is allowed only within centrally enforced safety bounds. Models and ordinary case reviewers cannot modify policy at runtime.

**Rationale**: Confidence, amount, reversibility, customer impact, and approval gates must be deterministic and reviewable. A model must not be able to widen its own authority.

**Alternatives considered**: Runtime model-defined thresholds and unbounded tenant administrator changes were rejected as unsafe; globally fixed thresholds were rejected because tenant policy configuration is an explicit requirement.

## Decision: Separation of duties and terminal case outcomes

**Decision**: Proposal, approval, and escalation roles are distinct. Escalations have a tenant-scoped owner. Terminal outcomes are `verified_contained`, `verified_failed`, and `escalated_unresolved`; generic successful closure is not used.

**Rationale**: High-impact actions require independent approval, and unresolved loss must remain visible and owned.

**Alternatives considered**: Single-operator approval/closure and a generic `closed` state were rejected because they permit self-approval and ambiguous resolution.

## Decision: Provider-neutral bounded model boundary

**Decision**: All model providers use one structured case, tool, policy, budget, and output interface behind the LangGraph/LiteLLM boundary. The model can analyze evidence and emit typed proposals only.

**Rationale**: Provider interchangeability and fair evaluation require identical inputs and safety gates. Side-effect credentials remain in connector/Action Gateway services, outside model reach.

**Alternatives considered**: Provider-specific prompts/tools and direct model-to-connector calls were rejected because they undermine comparison, least privilege, and deterministic validation.

## Decision: Deterministic replay and evaluation package

**Decision**: Create one canonical end-to-end fixture with deterministic variants for invalid signatures, duplicate/out-of-order events, missing evidence, policy denial, approval gating, unknown remote results, forbidden proposals, verification failure, escalation, and provider unavailability. Target a benchmark corpus of at least 500 cases when feasible, with a 60/20/20 development/validation/sealed-held-out split acceptable. Target at least 100 held-out cases, preferably 150 or more. Apply leakage-safe entity/customer and temporal separation before synthetic overlay generation; maintain at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases; keep held-out seeds/scenarios inaccessible to prompts, tuning, and model selection; report confidence intervals with metrics.

**Rationale**: The same interfaces and failure modes must be testable without live credentials or unsafe mutations. Entity/customer and temporal separation prevents leakage between related records and future information, including before synthetic overlays are added. The composition requirements preserve no-compromise false-alert behavior and mixed legitimate/malicious cases.

**Alternatives considered**: Happy-path-only replay, random event-level splits, overlays before leakage-safe separation, inaccessible holdout seeds exposed to tuning, and numeric padding were rejected because they do not test recovery or provide fair held-out evaluation.

## Decision: Targets versus measured baselines

**Decision**: Treat p95 simulator intake acknowledgement <=2 seconds and canonical replay completion <=5 minutes as provisional targets. Record actual p50/p95 latency, throughput, recovery time, and failure rates on a documented environment before adopting release thresholds.

**Rationale**: The repository explicitly prohibits presenting unmeasured performance as fact.

**Alternatives considered**: Calling targets production SLOs before a baseline was rejected as unverifiable.

## Decision: Authoritative provider correlation for webhook association

**Decision**: Version the accepted Razorpay webhook contract as `2.0.0` and derive a
`VerifiedProviderCorrelation` object at v1.0.0 only after original-payload
authenticity succeeds. For FS-001 payment events, the minimum identity is the
configured Razorpay connection, provider event ID, and provider payment ID; provider
order ID and a signed merchant reference are retained and checked when present.
Resolve that identity through exactly one active PostgreSQL
`ProviderCorrelationMapping` containing the authoritative tenant, incident, case, and
related order/payment context. Caller-supplied tenant, merchant, incident, and case
values are context/assertions only. Missing, ambiguous, revoked, conflicting, or
cross-tenant mappings quarantine without guessing.

**Rationale**: A valid signature authenticates provider origin but does not prove which
merchant case owns the event. The existing provider-event-only and case-optional
contract permits arbitrary same-tenant case substitution. Provider-native payment/order
identifiers bind the webhook to merchant-owned context, while PostgreSQL remains the
only source of case and tenant ownership.

**Alternatives considered**: Trusting caller-supplied case/incident IDs, using the
transport correlation ID, using tenant/merchant fields as lookup authority, or
creating a new universal correlation service were rejected. A temporary compatibility
mode that preserves caller-selected association was also rejected as insecure. Existing
case-only callers must migrate by provisioning the authoritative mapping; their IDs may
remain only as consistency assertions.

**Architecture impact**: No ownership boundary changes. PostgreSQL remains authoritative,
Temporal remains orchestration, Redpanda remains transport, and Neo4j remains a
rebuildable projection. No ADR change is required for D3.

## Implementation validation items deferred to coding

- Confirm configured Razorpay Test Mode signature/header and secret rotation behavior from the approved merchant connector documentation.
- Confirm the configured Razorpay Test Mode payload paths and event-family rules for
  payment ID, order ID, and signed merchant/reference fields before implementing the
  v2.0.0 extractor; do not infer provider behavior from replay fixtures alone.
- Pin runtime/library/container versions and verify compatibility in the Compose environment.
- Define the concrete benchmark provenance and labeling process; target at least 500 cases when feasible and at least 100 held-out cases, preferably 150 or more. If fewer cases exist, report the actual sample size, confidence-interval limitations, and shortfall; do not pad results.
- Select exact test runners and dashboard queries without changing contract or ownership decisions.
