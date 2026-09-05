# ADR-004: n8n Durable Orchestration Boundary

**Status**: Accepted
**Date**: 2026-09-03
**Supersedes**: ADR-001's Temporal workflow ownership for new executions

## Context

RECLAIM needs durable event-driven retries and recovery for incident analysis, but
business state and side effects must remain in the existing PostgreSQL and Action
Gateway boundaries. The project-wide orchestration decision is n8n, not a localhost
shortcut: new `incident.accepted` events must route to n8n, while already-running
Temporal workflows need a controlled drain period.

## Decision

n8n owns durable orchestration for new incident-analysis handoffs. A versioned Kafka
Trigger consumes Redpanda's `incident.accepted` envelope, and every node calls an
allowlisted, idempotent RECLAIM API. RECLAIM persists `orchestration_runs` and stage
attempts in PostgreSQL, validates tenant/case identity, expected state, stage order,
failure codes, and idempotency, and exposes only redacted structured intake to the
workflow. The workflow stops at `awaiting_human`; approvals and Action Gateway
execution remain explicit operator actions.

n8n uses a tenant-scoped service identity and has no direct PostgreSQL, MinIO,
model-provider, approval, or Action Gateway credentials. Redis is queue coordination
only. A failed or unavailable model records `requires_attention`; it never silently
replays or fabricates analysis. Temporal remains a `legacy-temporal` Compose profile
and is not an allowed target for newly accepted incidents until the drain exit
criteria are met.

## Consequences

The application services behind the former Temporal activities remain reusable and
testable without a workflow SDK. n8n workflow JSON and credentials are versioned and
bootstrapped idempotently. Operations must monitor both n8n recovery state and the
authoritative RECLAIM run record during the drain period. Once the Temporal run
inventory is empty and the parity/recovery gate passes, the legacy profile and SDK
can be removed in a separately recorded cleanup change.

## Rejected alternatives

- Keeping Temporal as the project-wide owner would contradict the approved v2.0.0
  architecture amendment.
- Letting n8n connect directly to PostgreSQL, MinIO, model providers, or the Action
  Gateway would bypass RECLAIM's tenant, policy, approval, and audit boundaries.
- Using Redis or n8n execution history as business truth would make recovery and
  duplicate delivery non-authoritative.
