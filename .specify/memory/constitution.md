<!--
Sync Impact Report
==================
Version change: placeholder constitution -> 1.0.0
Modified principles: all placeholder principles replaced with RECLAIM governance
principles I-X.
Added sections: Additional Constraints; Development Workflow.
Removed sections: none; placeholder content was replaced because it contained no
project-specific policy.
Follow-up TODOs: Staff Review and Project Status extensions are cataloged but not
installed; their commands remain unavailable until explicitly installed.
-->

# RECLAIM Constitution

## Core Principles

### I. Defense-Only Operation

RECLAIM MUST operate only on merchant-controlled systems through explicitly configured
connectors. It MUST NOT perform hack-back, offensive security actions, attacker
interaction, credential probing, arbitrary external-system access, unauthorized network
activity, or any action intended to harm or surveil an attacker. Every connector MUST
define its allowed resources and operations.

### II. Harnessed Agent and Action Gateway

The LLM or agent MUST analyze structured evidence and emit typed proposals only. It MUST
never directly execute payments, refunds, cancellations, account mutations, database
writes, shell commands, or arbitrary network calls. Every side effect MUST pass through
typed proposal validation, the versioned deterministic policy engine, required approval,
the isolated idempotent Action Gateway, verification, and audit recording. No API route,
tool, prompt, or model provider may bypass this sequence.

### III. Deterministic Financial Integrity

Financial calculations MUST be deterministic, reproducible, and implemented using integer
minor currency units with explicit currency. Exposure, recoverable value, contained
value, legitimate value disrupted, irreversible loss, and remaining exposure MUST be
computed by trusted application code rather than accepted from model prose. Refunds MUST
reference an existing captured payment, MUST be bounded by the unreimbursed amount, and
MUST return funds only to the original payment source.

### IV. Authoritative State and Durable Workflows

PostgreSQL MUST remain the authoritative source for business state, policy decisions,
approvals, action executions, and audit records. Temporal MUST own durable workflow
orchestration, retries, signals, timers, and recovery across process restarts. Redis MAY
provide bounded caching, locks, rate limiting, and coordination, but MUST never be the
sole source of correctness or financial state.

### V. Event and Projection Ownership

Redpanda MUST transport asynchronous domain events using versioned envelopes and
transactional outbox/inbox handling; it MUST NOT become the authoritative business
database. Neo4j MUST remain a rebuildable relationship projection whose loss can be
recovered from PostgreSQL and evidence. MinIO or equivalent object storage MUST retain
raw evidence and artifacts with checksums, while normalized searchable facts remain in
the authoritative store.

### VI. Policy, Approval, Idempotency, and Verification

Every proposed action MUST be checked against a versioned policy that evaluates
confidence, permissions, amount, resource state, reversibility, customer impact, and
approval requirements. High-impact actions, including cancellation, refund, and
identity-affecting restoration, MUST require policy-defined approval. Action requests MUST
use stable idempotency keys. If a remote result is unknown, RECLAIM MUST reconcile state
before retrying. Every attempted action MUST end in verified success, verified failure, or
escalation; ambiguous execution MUST never be silently treated as success.

### VII. Tenant Isolation, Least Privilege, and Untrusted Evidence

Tenant identity MUST be present in every business record, event, tool request, policy,
secret scope, and audit entry. Database access MUST enforce tenant isolation, and each
service MUST receive only the credentials and network access it requires. PII MUST be
minimized or redacted before model calls and traces. Evidence, customer text, webhook
content, and retrieved documents MUST be treated as untrusted input and MUST NOT be
allowed to redefine system instructions or tool permissions.

### VIII. Interchangeable Models and Fair Evaluation

Model providers MUST be replaceable behind a stable structured interface. Qwen,
Nemotron, DeepSeek, Llama-family, frontier APIs, and future providers MUST receive the
same case representation, schemas, tools, policies, budgets, and safety gateway. Model
comparisons MUST use the same sealed held-out cases and evaluation procedure. Fine-tuning
or distillation MUST remain optional and MUST NOT be required for the initial system.

### IX. Honest Metrics and Reproducible Audit

The system MUST measure malicious-action precision and recall, fraud value contained,
legitimate value disrupted, resolution success, latency, tool efficiency, forbidden
action attempts and executions, and model cost. Synthetic or hybrid benchmark results
MUST be labeled as such and MUST NOT be described as real production fraud performance.
The system MUST never fabricate metrics, benchmark results, test results, integrations,
or operational claims. Audit history MUST be append-only, evidence-linked, versioned, and
replayable from recorded inputs, policies, approvals, model outputs, and outcomes.

### X. Test-First Delivery and Explicit Architecture Decisions

Behavior changes MUST include appropriate unit, contract, integration, failure-recovery,
security, and acceptance tests. Safety checks and relevant acceptance criteria MUST pass
before tasks are marked complete. Performance thresholds are targets until supported by
baseline measurements. Material changes to the approved architecture, data ownership,
action boundary, or evaluation protocol MUST be recorded as explicit decisions and MUST
NOT be introduced silently.

## Additional Constraints

- The selected initial architecture is Next.js/TypeScript, FastAPI/Pydantic, Temporal
  Python SDK, LangGraph, LiteLLM, LightGBM, PostgreSQL, Redis, Redpanda, Neo4j, MinIO,
  Keycloak/OIDC, Vault, OpenTelemetry, Prometheus/Grafana/Loki, Langfuse, MLflow,
  Docker Compose, and GitHub Actions.
- Docker Compose is the authoritative initial deployment. Kubernetes and KServe-compatible
  artifacts are scale-out paths and MUST preserve the same contracts and safety gates.
- The initial system MUST support a tenant-ready schema with one demo merchant. It MUST
  provide live model execution with deterministic replay when provider availability or
  network conditions prevent a live run.
- Automated actions are limited to the explicitly allowlisted defensive operations. Live
  financial execution is disabled by default and requires separately configured policy,
  credentials, approvals, and verification.

## Development Workflow

The expected lifecycle is:

`specify → clarify → plan → tasks → analyze → implement → converge → staff review →
fixes → tests/evals → project-status update`

Each stage MUST consume the artifacts produced by the prior stage. A lifecycle command
that is not installed MUST be reported as unavailable; no manual action may be presented
as if that extension command had run. Feature specifications, plans, tasks, analyses,
reviews, tests, evaluations, and status updates MUST remain traceable to the same
feature and architecture decisions.

## Governance

This constitution is the highest-priority repository policy for RECLAIM. Amendments MUST
be proposed explicitly, include a sync impact report, use semantic versioning, and state
the rationale and migration impact. A new principle or material expansion increments the
minor version; a breaking removal or redefinition increments the major version; a
clarification increments the patch version. Compliance MUST be reviewed during planning,
task analysis, implementation, convergence, and staff review. No implementation task may
override this constitution without a separately approved amendment.

**Version**: 1.0.0 | **Ratified**: 2026-08-30 | **Last Amended**: 2026-08-30
