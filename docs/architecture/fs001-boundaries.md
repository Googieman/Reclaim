# FS-001 Architecture and authority boundaries

FS-001 preserves the approved RECLAIM architecture and implements it through vertical
slices. This document records the setup baseline; concrete contracts and services must
continue to satisfy the feature-local artifacts.

## Authority

- PostgreSQL is authoritative for tenant, case, evidence metadata, timeline, attribution,
  exposure, policy, approval, action, verification, escalation, audit, replay, and
  evaluation state.
- Temporal owns durable workflow orchestration, retries, timers, signals, and recovery.
- Redpanda transports versioned events through transactional outbox/inbox handling; it is
  not business authority. Consumers require an authenticated allowlisted service,
  allowlisted producer, supported schema/checksum, and exact PostgreSQL outbox
  reconciliation before any downstream projection write.
- Neo4j is a rebuildable relationship projection.
- MinIO stores immutable raw evidence and artifacts addressed by checksum.
- Redis is limited to bounded cache, locks, rate limiting, and coordination.

## Safety boundary

The model receives redacted structured evidence and typed read/proposal interfaces only.
It has no action credentials, database-write authority, shell access, arbitrary network
access, or direct connector access. Typed proposals pass deterministic validation,
versioned policy, required independent approval, stable idempotency, the isolated Action
Gateway, verification, and append-only audit before any merchant-controlled mutation.
Live financial execution remains disabled by default.

## Source decisions

- [ADR-001](../../specs/001-incident-intake-containment/decisions/ADR-001-authoritative-ownership.md)
  defines authoritative ownership and projection boundaries.
- [ADR-002](../../specs/001-incident-intake-containment/decisions/ADR-002-isolated-action-boundary.md)
  defines the bounded model and Action Gateway boundary.
- [ADR-003](../../specs/001-incident-intake-containment/decisions/ADR-003-replay-evaluation-baselines.md)
  defines labeled replay, grouped evaluation, and honest baselines.
- [Feature specification](../../specs/001-incident-intake-containment/spec.md),
  [plan](../../specs/001-incident-intake-containment/plan.md), and
  [tasks](../../specs/001-incident-intake-containment/tasks.md) are the governing FS-001
  artifacts.
